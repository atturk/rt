Questo documento è già il piano di implementazione completo e concordato: procedi direttamente alle modifiche, senza produrre un piano separato da approvare prima.

# TASK: Invarianti forti su `Segment` + pipeline CI GitHub Actions

## Contesto

Prima di iniziare il lavoro sul nuovo modulo di review (più veloce/dinamico, con ascolto diretto degli spezzoni audio) e sull'infrastruttura di split audio che ci sarà collegata, sistemiamo due punti a basso rischio emersi dall'audit esterno, diventati rilevanti proprio in vista di quel lavoro:

1. **Invarianti di `Segment`**: lo split audio taglierà clip basandosi su `start_seconds`/`end_seconds` — vale la pena garantire che questi dati siano internamente coerenti prima di costruirci sopra.
2. **CI automatica**: stiamo per aumentare il ritmo di sviluppo (review module, split audio, poi bot Telegram) — una rete di sicurezza automatica su ogni push diventa più utile ora.

Questi due interventi sono indipendenti tra loro, raggruppati in un solo task perché entrambi piccoli e a basso rischio.

---

## A. Invarianti forti su `Segment`

### Causa
`Segment` in `rt/core/models.py` (righe 13-32) valida solo `end_seconds > start_seconds`. Non verifica che `id` corrisponda davvero a `index` (es. `index=5` dovrebbe implicare `id="seg_000005"`), né che `start_formatted`/`end_formatted` corrispondano davvero a `start_seconds`/`end_seconds` convertiti in formato leggibile. Un `Segment` internamente incoerente potrebbe quindi passare la validazione Pydantic.

**Verificato prima di procedere**: ho controllato tutti i punti del codice che costruiscono `Segment` (`rt/core/segments.py`, 3 siti: JSON MacWhisper, JSON con timestamp stringa, Markdown legacy) — costruiscono sempre `id`/`index` e `start_formatted`/`end_formatted` in modo coerente tramite `make_segment_id()` e `format_timestamp()`. Ho anche verificato con uno script diretto tutti i `segments.json` reali già presenti nella repo (`test_real_lecture/` e le cartelle in `scratch/`, 512 segmenti totali): **zero incoerenze rilevate**. Il nuovo controllo è quindi sicuro da aggiungere come vincolo rigido (nessun dato esistente lo violerebbe).

### Fix
In `rt/core/models.py`, aggiungere un `model_validator(mode="after")` alla classe `Segment` (serve importare `model_validator` da pydantic, già usato altrove nel progetto, es. `rt/core/config.py`; e importare `format_timestamp` da `rt.core.timestamp` — nessun rischio di import circolare, verificato: `rt/core/timestamp.py` non importa nulla dal progetto):

```python
from pydantic import BaseModel, Field, field_validator, model_validator
from rt.core.timestamp import format_timestamp

class Segment(BaseModel):
    id: str = Field(..., description="ID univoco e stabile (es. seg_000001)")
    index: int = Field(..., ge=1, description="Indice progressivo a partire da 1")
    start_seconds: float = Field(..., ge=0.0, description="Timestamp iniziale in secondi")
    end_seconds: float = Field(..., gt=0.0, description="Timestamp finale in secondi")
    start_formatted: str = Field(..., description="Formato MM:SS o H:MM:SS")
    end_formatted: str = Field(..., description="Formato MM:SS o H:MM:SS")
    text_raw: str = Field(..., description="Trascrizione ASR grezza immutata")
    source_file: Optional[str] = None
    speaker: Optional[str] = None
    confidence: Optional[float] = None
    flags: List[str] = Field(default_factory=list)

    @field_validator("end_seconds")
    @classmethod
    def validate_end_after_start(cls, v: float, info) -> float:
        start = info.data.get("start_seconds")
        if start is not None and v <= start:
            raise ValueError(f"end_seconds ({v}) deve essere strettamente maggiore di start_seconds ({start})")
        return v

    @model_validator(mode="after")
    def validate_cross_field_consistency(self) -> "Segment":
        expected_id = f"seg_{self.index:06d}"
        if self.id != expected_id:
            raise ValueError(
                f"Segment incoerente: id='{self.id}' non corrisponde all'index={self.index} "
                f"(atteso '{expected_id}')"
            )
        expected_start_fmt = format_timestamp(self.start_seconds)
        if self.start_formatted != expected_start_fmt:
            raise ValueError(
                f"Segment incoerente: start_formatted='{self.start_formatted}' non corrisponde a "
                f"start_seconds={self.start_seconds} (atteso '{expected_start_fmt}')"
            )
        expected_end_fmt = format_timestamp(self.end_seconds)
        if self.end_formatted != expected_end_fmt:
            raise ValueError(
                f"Segment incoerente: end_formatted='{self.end_formatted}' non corrisponde a "
                f"end_seconds={self.end_seconds} (atteso '{expected_end_fmt}')"
            )
        return self
```

### Edge case e invarianti da rispettare
- Il confronto sui campi `_formatted` deve essere una normale uguaglianza di stringhe (`format_timestamp` tronca già a secondi interi, quindi non ci sono falsi positivi dovuti a precisione float residua — verificato).
- Non toccare `validate_end_after_start` (già corretto, invariato).
- Non toccare nessuno dei 3 siti di costruzione `Segment` in `rt/core/segments.py` — già producono dati coerenti, non serve modificarli.

### Test di accettazione
In `tests/test_segments.py` (o un file dedicato per i test di `Segment`), aggiungere:
1. Un test che costruisce un `Segment` con `id`/`index` incoerenti (es. `index=5, id="seg_000001"`) e verifica che sollevi `ValueError` con `pytest.raises`.
2. Un test che costruisce un `Segment` con `start_formatted` incoerente rispetto a `start_seconds` e verifica che sollevi `ValueError`.
3. Un test che costruisce un `Segment` correttamente coerente (usando `make_segment_id`/`format_timestamp` per calcolare i valori attesi) e verifica che la costruzione riesca senza eccezioni.
4. Rieseguire `python3 -m pytest tests/ -q` e confermare che TUTTI i test esistenti (171 attuali) continuino a passare — in particolare quelli che caricano `segments.json` da fixture o da `tmp_path` nei test esistenti, che devono già essere coerenti.

---

## B. Pipeline CI con GitHub Actions

### Fix
Creare `.github/workflows/tests.yml`:
```yaml
name: Test Suite

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install dependencies
        run: pip install -r requirements-dev.txt
      - name: Run test suite
        run: python -m pytest tests/ -q
```
Matrice su due versioni Python (3.10, il minimo dichiarato nel README, e 3.12) per verificare davvero la compatibilità dichiarata, non solo assumerla.

### Edge case e invarianti
- Nessuna chiave/segreto necessario: la suite di test usa esclusivamente mock (`monkeypatch`/`patch`), nessuna chiamata di rete reale — verificato che nessun test richieda variabili d'ambiente con credenziali vere per passare.
- Il workflow gira su push/PR verso `main` — non serve altro trigger per un progetto personale a singolo branch.
- Non serve badge nel README per questo task (opzionale, fuori scope se non richiesto esplicitamente).

### Verifica
Non eseguibile in locale (richiede GitHub Actions reale) — verificabile solo dopo il push controllando la tab "Actions" della repo. Assicurarsi solo che il file YAML sia sintatticamente valido e che `requirements-dev.txt` (già presente in repo) contenga tutto il necessario per eseguire `pytest tests/`.

---

## Verifica finale del task
Rieseguire l'intera suite (`python3 -m pytest tests/ -q`) e confermare zero regressioni (171 attuali + i nuovi test del punto A).
