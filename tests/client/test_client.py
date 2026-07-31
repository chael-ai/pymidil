import pytest
from unittest.mock import AsyncMock, Mock
import httpx
from httpx import URL
from pymidil.client.http import AsyncHTTPClient
from pymidil.client.exceptions import HTTPRequestError, HTTPStatusError
from pymidil.auth.interfaces.types import AuthNToken
from pymidil.auth.interfaces.authenticator import AuthNProvider


class MockAuthNProvider(AuthNProvider):
    """Mock AuthNProvider for testing."""

    def __init__(self, token: str = "test-token", token_type: str = "Bearer"):
        self.token = token
        self.token_type = token_type

    async def get_token(self) -> AuthNToken:
        return AuthNToken(token=self.token, token_type=self.token_type)


class TestHttpClient:
    """Tests for AsyncHTTPClient class."""

    @pytest.fixture
    def mock_auth_provider(self):
        """Create a mock authentication provider."""
        return MockAuthNProvider()

    @pytest.fixture
    def base_url(self):
        """Create a base URL for testing."""
        return "https://api.example.com"

    @pytest.fixture
    def http_client(self, mock_auth_provider: AuthNProvider, base_url: str):
        """Create an AsyncHTTPClient instance for testing."""
        return AsyncHTTPClient(
            auth_provider=mock_auth_provider,
            base_url=base_url,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    def test_init(
        self,
        http_client: AsyncHTTPClient,
        mock_auth_provider: AuthNProvider,
        base_url: str,
    ):
        """Test AsyncHTTPClient initialization."""
        client = http_client
        assert client.client.base_url == URL(base_url)
        assert client._auth_provider == mock_auth_provider
        assert isinstance(client.client, httpx.AsyncClient)
        assert client.client.base_url == base_url

    def test_client_property_getter(self, http_client: AsyncHTTPClient):
        """Test client property getter."""
        client = http_client.client
        assert isinstance(client, httpx.AsyncClient)
        assert client == http_client.client

    @pytest.mark.asyncio
    async def test_headers_property(self, http_client: AsyncHTTPClient):
        """Test resolve_headers returns auth headers."""
        headers = await http_client.resolve_headers()

        assert isinstance(headers, dict)
        assert "Authorization" in headers
        assert "Accept" in headers
        assert "Content-Type" in headers
        assert headers["Authorization"] == "Bearer test-token"

    @pytest.mark.asyncio
    async def test_headers_property_with_custom_auth(
        self, http_client: AsyncHTTPClient, base_url: str
    ):
        """Test resolve_headers with custom auth provider and base headers."""
        auth_provider = MockAuthNProvider(token="custom-token")
        client = AsyncHTTPClient(
            auth_provider=auth_provider,
            base_url=base_url,
            headers={
                "Accept": "application/vnd.api+json",
                "X-Custom-Header": "custom-value",
            },
        )

        headers = await client.resolve_headers()

        assert headers["Authorization"] == "Bearer custom-token"
        assert headers["Accept"] == "application/vnd.api+json"
        assert headers["X-Custom-Header"] == "custom-value"

    @pytest.mark.asyncio
    async def test_send_request_success(self, http_client: AsyncHTTPClient):
        """Test successful request sending returns the raw response."""
        mock_response = Mock()
        mock_response.json.return_value = {"success": True, "data": "test"}
        mock_response.raise_for_status.return_value = None

        http_client.client.request = AsyncMock(return_value=mock_response)

        result = await http_client.send_request(
            method="POST", url="/test", json={"test": "data"}
        )

        assert result is mock_response
        assert result.json() == {"success": True, "data": "test"}

        http_client.client.request.assert_called_once_with(
            method="POST",
            url="/test",
            headers={
                "Authorization": "Bearer test-token",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={"test": "data"},
        )

    @pytest.mark.asyncio
    async def test_send_request_get_method(self, http_client: AsyncHTTPClient):
        """Test GET request."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": "retrieved"}
        mock_response.raise_for_status.return_value = None

        http_client.client.request = AsyncMock(return_value=mock_response)

        result = await http_client.send_request(method="GET", url="/users/123", json={})

        assert result.json() == {"data": "retrieved"}

        http_client.client.request.assert_called_once_with(
            method="GET",
            url="/users/123",
            headers={
                "Authorization": "Bearer test-token",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={},
        )

    @pytest.mark.asyncio
    async def test_send_request_with_different_methods(
        self, http_client: AsyncHTTPClient
    ):
        """Test request with different HTTP methods."""
        mock_response = Mock()
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status.return_value = None

        http_client.client.request = AsyncMock(return_value=mock_response)

        methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]

        for method in methods:
            await http_client.send_request(
                method=method, url=f"/test-{method.lower()}", json={"method": method}
            )

            last_call = http_client.client.request.call_args
            assert last_call[1]["method"] == method
            assert last_call[1]["url"] == f"/test-{method.lower()}"

    @pytest.mark.asyncio
    async def test_send_request_http_status_error(self, http_client: AsyncHTTPClient):
        """A non-2xx response is raised as a domain HTTPStatusError, not raw httpx."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found",
            request=httpx.Request("GET", "https://example.com"),
            response=httpx.Response(status_code=404),
        )

        http_client.client.request = AsyncMock(return_value=mock_response)

        with pytest.raises(HTTPStatusError) as exc_info:
            await http_client.send_request(method="GET", url="/not-found", json={})

        assert exc_info.value.status_code == 404
        assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)

    @pytest.mark.asyncio
    async def test_send_request_network_error(self, http_client: AsyncHTTPClient):
        """A transport-level failure is raised as a domain HTTPRequestError."""
        http_client.client.request = AsyncMock(
            side_effect=httpx.ConnectError("Connection failed")
        )

        with pytest.raises(HTTPRequestError) as exc_info:
            await http_client.send_request(method="GET", url="/test", json={})

        assert isinstance(exc_info.value.__cause__, httpx.ConnectError)

    @pytest.mark.asyncio
    async def test_send_request_leaves_body_parsing_to_caller(
        self, http_client: AsyncHTTPClient
    ):
        """send_request doesn't parse the body, so a non-JSON response doesn't
        blow up until (and unless) the caller calls .json()."""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.side_effect = ValueError("Invalid JSON")

        http_client.client.request = AsyncMock(return_value=mock_response)

        result = await http_client.send_request(method="GET", url="/test", json={})

        assert result is mock_response
        with pytest.raises(ValueError):
            result.json()

    @pytest.mark.asyncio
    async def test_send_request_uses_fresh_headers(self, http_client: AsyncHTTPClient):
        """Test that send_request resolves headers for each request."""
        mock_response = Mock()
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status.return_value = None

        http_client.client.request = AsyncMock(return_value=mock_response)

        await http_client.send_request("GET", "/test1", json={})
        await http_client.send_request("GET", "/test2", json={})

        assert http_client.client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_send_paginated_request_not_implemented(
        self, http_client: AsyncHTTPClient
    ):
        """Test that send_paginated_request raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await http_client.send_paginated_request(
                method="GET", url="/paginated", json={}
            )

    def test_type_annotations(self, http_client: AsyncHTTPClient):
        """Test that type annotations are properly set."""
        import inspect

        init_sig = inspect.signature(AsyncHTTPClient.__init__)
        assert "auth_provider" in init_sig.parameters
        assert "base_url" in init_sig.parameters

        assert hasattr(http_client, "send_request")
        assert hasattr(http_client, "send_paginated_request")
        assert hasattr(
            AsyncHTTPClient, "resolve_headers"
        )  # Check class level to avoid coroutine creation

    @pytest.mark.asyncio
    async def test_auth_provider_integration(
        self, http_client: AsyncHTTPClient, base_url: str
    ):
        """Test integration with different auth providers."""

        class CustomAuthProvider(AuthNProvider):
            async def get_token(self) -> AuthNToken:
                return AuthNToken(token="integration-token")

        custom_auth = CustomAuthProvider()  # type: ignore
        client = AsyncHTTPClient(
            auth_provider=custom_auth,
            base_url=base_url,
            headers={
                "Accept": "application/custom+json",
                "Content-Type": "application/custom+json",
            },
        )

        headers = await client.resolve_headers()

        assert headers["Authorization"] == "Bearer integration-token"
        assert headers["Accept"] == "application/custom+json"
        assert headers["Content-Type"] == "application/custom+json"

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, http_client: AsyncHTTPClient):
        """Test handling concurrent requests."""
        import anyio

        mock_response = Mock()
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status.return_value = None

        http_client.client.request = AsyncMock(return_value=mock_response)

        results = []

        async def make_request(i):
            result = await http_client.send_request("GET", f"/test-{i}", json={})
            results.append(result)

        async with anyio.create_task_group() as tg:
            for i in range(5):
                tg.start_soon(make_request, i)

        assert all(result is mock_response for result in results)
        assert http_client.client.request.call_count == 5

    def test_base_url_handling_with_different_url_types(
        self, mock_auth_provider: AuthNProvider
    ):
        """Test base_url handling with different URL types."""
        string_url = "https://api.example.com"
        client1 = AsyncHTTPClient(
            auth_provider=mock_auth_provider, base_url=URL(string_url)
        )
        assert str(client1.base_url) == string_url

        url_obj = URL("https://api.example.com")
        client2 = AsyncHTTPClient(auth_provider=mock_auth_provider, base_url=url_obj)
        assert client2.base_url == url_obj

    @pytest.mark.asyncio
    async def test_complex_data_structures(self, http_client: AsyncHTTPClient):
        """Test sending complex data structures."""
        mock_response = Mock()
        mock_response.json.return_value = {"processed": True}
        mock_response.raise_for_status.return_value = None

        setattr(http_client.client, "request", AsyncMock(return_value=mock_response))

        complex_data = {
            "user": {
                "name": "John Doe",
                "email": "john@example.com",
                "preferences": {"theme": "dark", "notifications": True},
            },
            "metadata": {"timestamp": "2023-01-01T00:00:00Z", "version": "1.0"},
        }

        result = await http_client.send_request("POST", "/complex", json=complex_data)

        assert result.json() == {"processed": True}

        call_args = http_client.client.request.call_args  # type: ignore
        assert call_args[1]["json"] == complex_data
