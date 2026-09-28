# Formule nell’anteprima

L’anteprima riconosce delimitatori matematici espliciti: `\(...\)` e `$...$` per formule
inline; `\[...\]` e `$$...$$` per formule in blocco. Il testo nei nodi `code` e `pre` non viene
interpretato.

Il renderer produce MathML e supporta gruppi `{...}`, potenze `^`, indici `_`, `\frac`, `\sqrt`,
comandi di testo `\text`, `\mathrm`, `\mathbf`, lettere greche comuni e operatori frequenti
(`\times`, `\cdot`, `\le`, `\ge`, `\neq`, `\approx`, `\to`, `\infty`, `\sum`, `\int`). I
delimitatori sono necessari: il testo normale non viene analizzato per indovinare formule.
