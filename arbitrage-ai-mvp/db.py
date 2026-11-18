"""Minimal Supabase PostgREST client. Service key stays server-side."""
import requests


class SupabaseError(RuntimeError):
    pass


class Supabase:
    def __init__(self, url, key, timeout=15):
        if not url or not key:
            raise ValueError("Supabase URL and service key are required")
        self.base = url.rstrip("/") + "/rest/v1"
        self.timeout = timeout
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def _request(self, method, table, params=None, body=None, prefer=None):
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        try:
            response = requests.request(
                method, f"{self.base}/{table}", params=params, json=body,
                headers=headers, timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise SupabaseError(
                f"{method} {table}: network error ({type(error).__name__})"
            ) from error
        if response.status_code >= 400:
            # Do not echo response bodies: they may contain schema details or data.
            raise SupabaseError(f"{method} {table}: HTTP {response.status_code}")
        if not response.text:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise SupabaseError(f"{method} {table}: invalid JSON response") from error

    def select(self, table, **params):
        params.setdefault("select", "*")
        return self._request("GET", table, params=params) or []

    def insert(self, table, rows):
        if not rows:
            return None
        return self._request("POST", table, body=rows, prefer="return=minimal")

    def upsert(self, table, rows, on_conflict):
        if not rows:
            return None
        if not on_conflict:
            raise ValueError("on_conflict is required")
        return self._request(
            "POST", table, params={"on_conflict": on_conflict}, body=rows,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def patch(self, table, filters, values):
        if not filters:
            raise ValueError("PATCH requires filters")
        if not values:
            return None
        return self._request(
            "PATCH", table, params=filters, body=values, prefer="return=minimal"
        )

    def delete(self, table, filters):
        if not filters:
            raise ValueError("DELETE requires filters")
        return self._request("DELETE", table, params=filters, prefer="return=minimal")
