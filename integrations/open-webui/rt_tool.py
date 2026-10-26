"""
title: RT
description: Cerca e legge le lezioni di RT con la chiave di sola lettura.
version: 1.0.0
"""

import requests
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        rt_url: str = Field(
            default="http://127.0.0.1:8765",
            description="Indirizzo di RT",
        )
        api_key: str = Field(
            default="",
            description="Chiave di sola lettura di RT (rt_ro_...)",
        )

    def __init__(self):
        self.valves = self.Valves()

    def _get(self, path: str, params: dict = None):
        if not self.valves.api_key:
            return None, "Manca la chiave di RT: inseriscila nelle valvole dello strumento."
        url = self.valves.rt_url.rstrip("/") + "/api/v1/readonly" + path
        try:
            r = requests.get(
                url,
                params={k: v for k, v in (params or {}).items() if v not in (None, "")},
                headers={"Authorization": f"Bearer {self.valves.api_key}"},
                timeout=30,
            )
        except requests.RequestException:
            return None, f"RT non risponde su {self.valves.rt_url}: è aperto?"
        if r.status_code == 401:
            return None, "Chiave di RT non valida o revocata."
        if r.status_code == 403:
            return None, "RT accetta la chiave solo da questo computer (127.0.0.1), senza proxy."
        if r.status_code >= 400:
            try:
                return None, r.json().get("error", {}).get("message") or r.text
            except ValueError:
                return None, f"Errore {r.status_code} da RT."
        return r.json(), None

    def search_lessons(
        self,
        query: str,
        subject: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 10,
    ) -> str:
        """
        Search the text of the user's recorded lessons in RT. Use it first for any question about what was explained in class.
        :param query: Words to search for, in Italian.
        :param subject: Optional subject filter, e.g. BIOCHIMICA.
        :param date_from: Optional minimum date, YYYY-MM-DD.
        :param date_to: Optional maximum date, YYYY-MM-DD.
        :param limit: Maximum number of results (1-50).
        :return: Matching units with lesson_id, unit_id, subject, date, title and snippet.
        """
        data, err = self._get(
            "/lessons/search",
            {"q": query, "subject": subject, "date_from": date_from,
             "date_to": date_to, "limit": max(1, min(int(limit or 10), 50))},
        )
        if err:
            return err
        if not data:
            return "Nessun risultato."
        return "\n".join(
            f"- lezione {h['lesson_id']}, unità {h['unit_id']} · {h['subject']} {h['date']} · "
            f"{h['title']}: {h['snippet']}"
            for h in data
        )

    def list_lessons(
        self,
        subject: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 50,
    ) -> str:
        """
        List the user's lessons in RT, newest first.
        :param subject: Optional subject filter, e.g. BIOCHIMICA.
        :param date_from: Optional minimum date, YYYY-MM-DD.
        :param date_to: Optional maximum date, YYYY-MM-DD.
        :param limit: Maximum number of lessons (1-100).
        :return: Lessons with id, date, subject and title.
        """
        data, err = self._get(
            "/lessons",
            {"subject": subject, "date_from": date_from, "date_to": date_to,
             "limit": max(1, min(int(limit or 50), 100))},
        )
        if err:
            return err
        if not data:
            return "Nessuna lezione."
        return "\n".join(
            f"- {l['id']} · {l['date']} · {l['subject']} · {l['title']}" for l in data
        )

    def get_lesson_outline(self, lesson_id: int) -> str:
        """
        Get the outline of one RT lesson: its units with their ids and titles.
        :param lesson_id: The lesson id.
        :return: The lesson title and its units.
        """
        data, err = self._get(f"/lessons/{int(lesson_id)}/outline")
        if err:
            return err
        units = "\n".join(f"- {u['unit_id']} {u['title']}" for u in data["units"])
        return f"{data['title']} ({data['subject']})\n{units or 'Nessuna unità.'}"

    def get_lesson_unit(self, lesson_id: int, unit_id: str) -> str:
        """
        Read the full text of one unit of an RT lesson. Use it to answer from the user's own notes.
        :param lesson_id: The lesson id.
        :param unit_id: The unit id, e.g. 1.1.
        :return: The unit title and full text.
        """
        data, err = self._get(
            f"/lessons/{int(lesson_id)}/units/{requests.utils.quote(str(unit_id), safe='')}"
        )
        if err:
            return err
        return f"{data['title']}\n\n{data['content']}"
