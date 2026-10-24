from __future__ import annotations

import ssl
import json
import re
from types import TracebackType
from typing import Any, Self

import aiohttp
import certifi

API_BASE_URL = "https://api.kwork.ru"
SITE_BASE_URL = "https://kwork.ru"
MOBILE_API_AUTH = "Basic bW9iaWxlX2FwaTpxRnZmUmw3dw=="


class KworkError(RuntimeError):
    """Ошибка сети, авторизации или ответа Kwork API."""


class KworkClient:
    """Минимальный клиент: авторизация и чтение откликов аккаунта."""

    def __init__(
        self,
        login: str = "",
        password: str = "",
        *,
        phone_last: str | None = None,
        token: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not token and (not login.strip() or not password):
            raise ValueError("Логин и пароль обязательны")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds должен быть больше нуля")
        self._login = login.strip()
        self._password = password
        self._phone_last = phone_last.strip() if phone_last else None
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session: aiohttp.ClientSession | None = None
        self._token: str | None = token

    @property
    def token(self) -> str | None:
        return self._token

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    @property
    def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            tls_context = ssl.create_default_context(cafile=certifi.where())
            self._session = aiohttp.ClientSession(
                base_url=API_BASE_URL,
                timeout=self._timeout,
                headers={"Authorization": MOBILE_API_AUTH},
                connector=aiohttp.TCPConnector(ssl=tls_context),
                raise_for_status=False,
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _request(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not endpoint.startswith("/") or "://" in endpoint:
            raise ValueError("Разрешены только относительные API endpoints")
        try:
            async with self._http.post(
                endpoint, params=params, data=form, allow_redirects=False
            ) as response:
                try:
                    payload: Any = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as error:
                    raise KworkError(
                        f"Kwork вернул некорректный ответ (HTTP {response.status})"
                    ) from error
        except (aiohttp.ClientError, TimeoutError) as error:
            raise KworkError(f"Не удалось подключиться к Kwork: {type(error).__name__}") from error

        if response.status < 200 or response.status >= 300:
            raise KworkError(f"Kwork API вернул HTTP {response.status}")
        if not isinstance(payload, dict):
            raise KworkError("Kwork API вернул неожиданный формат данных")
        if payload.get("success") is not True:
            message = payload.get("error") or "неизвестная ошибка API"
            raise KworkError(f"Kwork API: {message}")
        return payload

    async def _get_token(self) -> str:
        if self._token is not None:
            return self._token
        credentials: dict[str, str] = {"login": self._login, "password": self._password}
        if self._phone_last:
            credentials["phone_last"] = self._phone_last
        payload = await self._request("/signIn", form=credentials)
        response = payload.get("response")
        token = response.get("token") if isinstance(response, dict) else None
        if not isinstance(token, str) or not token:
            raise KworkError("Kwork не вернул токен авторизации")
        self._token = token
        return token

    async def get_offers_page(self, page: int = 1) -> dict[str, Any]:
        """Получить одну страницу откликов текущего аккаунта."""
        if page < 1:
            raise ValueError("Номер страницы должен быть не меньше 1")
        return await self._request(
            "/offers", params={"token": await self._get_token()}, form={"page": page}
        )

    async def get_all_offers(self) -> list[dict[str, Any]]:
        """Получить все доступные страницы откликов текущего аккаунта."""
        offers: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = await self.get_offers_page(page)
            current = payload.get("response")
            if not isinstance(current, list):
                raise KworkError("Поле response в /offers не является списком")
            offers.extend(item for item in current if isinstance(item, dict))
            paging = payload.get("paging")
            pages = paging.get("pages") if isinstance(paging, dict) else None
            if not current or not isinstance(pages, int) or page >= pages:
                break
            page += 1
        return offers

    async def get_actor(self) -> dict[str, Any]:
        payload = await self._request("/actor", params={"token": await self._get_token()})
        actor = payload.get("response")
        if not isinstance(actor, dict):
            raise KworkError("Kwork не вернул профиль аккаунта")
        return actor

    async def get_kworks_page(self, user_id: int, page: int = 1) -> dict[str, Any]:
        if page < 1:
            raise ValueError("Номер страницы должен быть не меньше 1")
        return await self._request(
            "/userKworks",
            params={"token": await self._get_token()},
            form={"user_id": user_id, "page": page},
        )

    @staticmethod
    def _kworks_from_response(response: Any) -> list[dict[str, Any]] | None:
        """Извлечь список из известных вариантов ответа мобильного API."""
        if isinstance(response, list):
            return [item for item in response if isinstance(item, dict)]
        if not isinstance(response, dict):
            return None
        for key in ("items", "kworks", "list", "data"):
            candidate = response.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
            if isinstance(candidate, dict):
                nested = KworkClient._kworks_from_response(candidate)
                if nested is not None:
                    return nested
        return None

    async def get_all_kworks(self, actor: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        kworks: list[dict[str, Any]] = []
        actor = actor or await self.get_actor()
        embedded_kworks = self._kworks_from_response(actor.get("kworks")) or []
        user_id = actor.get("id") or actor.get("USERID") or actor.get("user_id")
        if not isinstance(user_id, int):
            try:
                user_id = int(user_id)
            except (TypeError, ValueError) as error:
                raise KworkError("Kwork не вернул ID аккаунта") from error
        page = 1
        while True:
            payload = await self.get_kworks_page(user_id, page)
            response = payload.get("response")
            current = self._kworks_from_response(response)
            if current is None:
                raise KworkError("Kwork вернул неожиданный список кворков")
            kworks.extend(current)
            paging = payload.get("paging") or (response.get("paging") if isinstance(response, dict) else None)
            raw_pages = paging.get("pages") if isinstance(paging, dict) else None
            try:
                pages = int(raw_pages)
            except (TypeError, ValueError):
                pages = 1
            if not current or page >= pages:
                break
            page += 1
        if not kworks:
            return embedded_kworks
        known_ids = {str(item.get("id") or item.get("PID")) for item in kworks}
        kworks.extend(item for item in embedded_kworks if str(item.get("id") or item.get("PID")) not in known_ids)
        return kworks

    async def get_user_reviews_page(self, user_id: int, page: int = 1, review_type: str = "all") -> dict[str, Any]:
        if page < 1 or review_type not in {"all", "positive", "negative"}:
            raise ValueError("Некорректная страница или тип отзывов")
        return await self._request(
            "/userReviews",
            params={"token": await self._get_token()},
            form={"user_id": user_id, "type": review_type, "page": page},
        )

    async def get_all_user_reviews(self, user_id: int) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = await self.get_user_reviews_page(user_id, page)
            current = payload.get("response")
            if not isinstance(current, list):
                raise KworkError("Kwork вернул неожиданный список отзывов")
            result.extend(item for item in current if isinstance(item, dict))
            paging = payload.get("paging")
            try:
                pages = int(paging.get("pages") if isinstance(paging, dict) else 1)
            except (TypeError, ValueError):
                pages = 1
            if not current or page >= pages:
                return result
            page += 1

    @staticmethod
    def _parse_project_state(html: str) -> dict[str, Any]:
        marker = "window.stateData="
        start = html.find(marker)
        if start < 0:
            raise KworkError("Kwork не вернул данные проекта")
        try:
            state, _ = json.JSONDecoder().raw_decode(html[start + len(marker) :])
        except (json.JSONDecodeError, TypeError) as error:
            raise KworkError("Не удалось разобрать данные проекта Kwork") from error
        want = state.get("wantData") if isinstance(state, dict) else None
        if not isinstance(want, dict):
            raise KworkError("В ответе Kwork отсутствует проект")
        count = want.get("wantGetSumOrderCount")
        return {
            "buyer_order_count": count if isinstance(count, int) else 0,
            "project_budget": want.get("priceLimit"),
            "project_status": want.get("status"),
        }

    async def get_project_market_data(self, project_id: int) -> dict[str, Any]:
        """Прочитать публичный факт заказов покупателя по проекту."""
        if project_id <= 0:
            raise ValueError("Некорректный ID проекта")
        tls_context = ssl.create_default_context(cafile=certifi.where())
        try:
            async with aiohttp.ClientSession(
                timeout=self._timeout,
                connector=aiohttp.TCPConnector(ssl=tls_context),
                headers={"User-Agent": "Mozilla/5.0 KworkPulse/1.0"},
            ) as session:
                async with session.get(
                    f"{SITE_BASE_URL}/projects/{project_id}/view",
                    allow_redirects=True,
                ) as response:
                    if response.status != 200:
                        raise KworkError(f"Страница проекта вернула HTTP {response.status}")
                    return self._parse_project_state(await response.text())
        except (aiohttp.ClientError, TimeoutError) as error:
            raise KworkError(
                f"Не удалось получить аналитику проекта: {type(error).__name__}"
            ) from error

    async def get_selected_orders(self, project_ids: list[int]) -> dict[int, dict[str, Any]]:
        """Получить те же выбранные предложения, которые показывает /offers Kwork."""
        clean_ids = list(dict.fromkeys(x for x in project_ids if isinstance(x, int) and x > 0))
        if not clean_ids:
            return {}
        token = await self._get_token()
        auth = await self._request(
            "/getWebAuthToken",
            params={"token": token, "url_to_redirect": "/offers"},
        )
        response = auth.get("response")
        auth_url = response.get("url") if isinstance(response, dict) else None
        if not isinstance(auth_url, str) or not auth_url.startswith(SITE_BASE_URL):
            raise KworkError("Kwork не вернул ссылку веб-авторизации")

        tls_context = ssl.create_default_context(cafile=certifi.where())
        try:
            async with aiohttp.ClientSession(
                timeout=self._timeout,
                connector=aiohttp.TCPConnector(ssl=tls_context),
                headers={"User-Agent": "Mozilla/5.0 KworkPulse/1.0"},
            ) as session:
                async with session.get(auth_url, allow_redirects=True) as web_response:
                    html = await web_response.text()
                    if web_response.status != 200:
                        raise KworkError(f"Веб-авторизация вернула HTTP {web_response.status}")
                match = re.search(r'window\.csrftoken="([^"]+)"', html)
                if not match:
                    raise KworkError("Kwork не вернул CSRF-токен")
                csrf = match.group(1)
                async with session.post(
                    f"{SITE_BASE_URL}/wants/get_offer_orders_info",
                    json={"want_ids": clean_ids, "csrftoken": csrf},
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRF-Token": csrf,
                        "Referer": f"{SITE_BASE_URL}/offers",
                    },
                ) as orders_response:
                    payload = await orders_response.json(content_type=None)
                    if orders_response.status != 200 or payload.get("success") is not True:
                        raise KworkError("Kwork не вернул выбранные предложения")
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            raise KworkError(
                f"Не удалось получить выбранные предложения: {type(error).__name__}"
            ) from error

        result: dict[int, dict[str, Any]] = {}
        data = payload.get("data")
        if not isinstance(data, dict):
            return result
        for raw_project_id, project in data.items():
            if not isinstance(project, dict):
                continue
            winners = []
            for offer in project.get("offers", []):
                if not isinstance(offer, dict) or not isinstance(offer.get("order"), dict):
                    continue
                user, order, kwork = offer.get("user") or {}, offer["order"], offer.get("kwork") or {}
                user_id = str(offer.get("userId") or "")
                reviews = (project.get("usersReviewsCounts") or {}).get(user_id, {})
                avatar = str(user.get("avatarSrcSet") or "").split(" ", 1)[0]
                winners.append({
                    "user_id": int(offer.get("userId") or user.get("id") or 0),
                    "username": user.get("username"),
                    "profile_url": user.get("profileUrl"),
                    "avatar_url": avatar,
                    "orders_done": int(user.get("orderDoneCount") or 0),
                    "success_percent": int((user.get("data") or {}).get("orderDonePersent") or 0),
                    "on_time_percent": int((user.get("data") or {}).get("orderDoneInTimePersent") or 0),
                    "rating": user.get("convertedUserRating"),
                    "reviews_good": int(reviews.get("good") or 0),
                    "reviews_bad": int(reviews.get("bad") or 0),
                    "days": round(float(order.get("duration") or 0) / 86400),
                    "price": float(order.get("crt") or order.get("price") or 0),
                    "customer_paid": float(order.get("price") or 0),
                    "service_title": kwork.get("gtitle"),
                    "service_url": f"{SITE_BASE_URL}/kwork/{kwork.get('PID')}" if kwork.get("PID") else None,
                })
            if winners:
                result[int(raw_project_id)] = {"winners": winners}
        return result
