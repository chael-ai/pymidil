import pytest
import contextvars
from unittest.mock import patch

from pymidil.event.context import (
    EventContext,
    get_current_event,
    event_context,
    _current_event_context,
)


pytestmark = pytest.mark.anyio


class TestEventContext:
    """Tests for EventContext class."""

    def test_init_minimal(self):
        """Test EventContext initialization with minimal parameters."""
        context = EventContext(id="test-id", event_type="test.event")

        assert context.id == "test-id"
        assert context.event_type == "test.event"
        assert context.parent is None

    def test_init_with_parent(self) -> None:
        """Test EventContext initialization with parent context."""
        parent = EventContext(id="parent-id", event_type="parent.event")
        child = EventContext(id="child-id", event_type="child.event", parent=parent)

        assert child.id == "child-id"
        assert child.event_type == "child.event"
        assert child.parent == parent
        assert child.parent.id == "parent-id"  # type: ignore

    def test_init_with_different_event_types(self) -> None:
        """Test EventContext with various event type formats."""
        event_types = [
            "user.created",
            "order.payment.completed",
            "system_health_check",
            "API_CALL",
            "database-migration-complete",
        ]

        for event_type in event_types:
            context = EventContext(id=f"id-{event_type}", event_type=event_type)
            assert context.event_type == event_type

    def test_parent_chain(self) -> None:
        """Test parent chain linking."""
        grandparent = EventContext(id="gp", event_type="grandparent.event")
        parent = EventContext(id="p", event_type="parent.event", parent=grandparent)
        child = EventContext(id="c", event_type="child.event", parent=parent)

        assert child.parent == parent
        assert child.parent.parent == grandparent  # type: ignore
        assert child.parent.parent.parent is None  # type: ignore

    def test_context_equality(self) -> None:
        """Test EventContext equality comparison."""
        context1 = EventContext(id="same-id", event_type="same.event")
        context2 = EventContext(id="same-id", event_type="same.event")
        context3 = EventContext(id="different-id", event_type="same.event")

        # EventContext doesn't implement __eq__, so they should be different objects
        assert context1 is not context2
        assert context1 is not context3

    def test_context_string_representation(self) -> None:
        """Test string representation of EventContext."""
        context = EventContext(id="test-123", event_type="test.event")
        str_repr = str(context)

        # Should contain the class name
        assert "EventContext" in str_repr


class TestGetCurrentEvent:
    """Tests for get_current_event function."""

    def test_get_current_event_when_not_set(self) -> None:
        """Test get_current_event returns None when no context is set."""
        # Make sure we're testing in a clean context by using contextvars.copy_context()
        # to run the test in an isolated context
        ctx = contextvars.copy_context()

        def test_in_clean_context() -> None:
            assert get_current_event() is None

        ctx.run(test_in_clean_context)

    def test_get_current_event_when_set(self) -> None:
        """Test get_current_event returns current context when set."""
        test_context = EventContext(id="test-id", event_type="test.event")
        token = _current_event_context.set(test_context)

        try:
            current = get_current_event()
            assert current == test_context
            assert current.id == "test-id"  # type: ignore
            assert current.event_type == "test.event"  # type: ignore
        finally:
            _current_event_context.reset(token)


class TestEventContextManager:
    """Tests for event_context async context manager."""

    async def test_event_context_basic_usage(self) -> None:
        """Test basic usage of event_context."""
        async with event_context("test.event") as ctx:
            assert isinstance(ctx, EventContext)
            assert ctx.event_type == "test.event"
            assert ctx.parent is None

            # Should be able to get the current context
            current = get_current_event()
            assert current == ctx

    async def test_event_context_generates_unique_ids(self) -> None:
        """Test that event_context generates unique IDs."""
        ids = []

        for i in range(5):
            async with event_context(f"test.event.{i}") as ctx:
                ids.append(ctx.id)

        # All IDs should be unique
        assert len(set(ids)) == 5

        # IDs should be valid hex strings (from uuid4().hex)
        for id_str in ids:
            # Should be 32 character hex string
            assert len(id_str) == 32
            # Should be valid hex
            int(id_str, 16)  # This will raise if not valid hex

    async def test_event_context_nesting(self) -> None:
        """Test nesting event contexts."""
        async with event_context("parent.event") as parent_ctx:
            assert parent_ctx.parent is None

            async with event_context("child.event") as child_ctx:
                assert child_ctx.parent == parent_ctx
                assert child_ctx.event_type == "child.event"

                # Current context should be the child
                current = get_current_event()
                assert current == child_ctx

            # After exiting child context, parent should be current again
            current = get_current_event()
            assert current == parent_ctx

    async def test_event_context_with_parent_override(self) -> None:
        """Test event_context with explicit parent override."""
        explicit_parent = EventContext(id="explicit", event_type="explicit.parent")

        async with event_context("outer.event") as outer_ctx:
            # Use explicit parent instead of outer context
            async with event_context(
                "inner.event", parent_override=explicit_parent
            ) as inner_ctx:
                assert inner_ctx.parent == explicit_parent
                assert inner_ctx.parent != outer_ctx

    async def test_event_context_cleanup_on_exception(self) -> None:
        """Test that context is properly cleaned up on exception."""
        with pytest.raises(ValueError, match="Test exception"):
            async with event_context("error.event") as ctx:
                # Verify context is set
                current = get_current_event()
                assert current == ctx

                # Raise exception to test cleanup
                raise ValueError("Test exception")

        # Context should be cleaned up after exception
        assert get_current_event() is None

    async def test_event_context_cleanup_on_normal_exit(self) -> None:
        """Test that context is properly cleaned up on normal exit."""
        async with event_context("normal.event"):
            # Context should be set inside
            current = get_current_event()
            assert current is not None

        # Context should be cleaned up after normal exit
        assert get_current_event() is None

    async def test_event_context_multiple_levels_cleanup(self) -> None:
        """Test cleanup with multiple nested levels."""
        async with event_context("level1") as ctx1:
            async with event_context("level2") as ctx2:
                async with event_context("level3") as ctx3:
                    current = get_current_event()
                    assert current == ctx3

                # After level3 exits, should be back to level2
                current = get_current_event()
                assert current == ctx2

            # After level2 exits, should be back to level1
            current = get_current_event()
            assert current == ctx1

        # After all exit, no context should be set
        assert get_current_event() is None

    async def test_event_context_concurrent_usage(self) -> None:
        """Test event context in concurrent scenarios."""
        import anyio

        results = []

        async def worker(event_type: str, worker_id: int) -> None:
            async with event_context(event_type):
                # Simulate some async work
                await anyio.sleep(0.01)

                current = get_current_event()
                assert current is not None
                results.append((worker_id, current.id, current.event_type))

        # Run multiple workers concurrently
        async with anyio.create_task_group() as tg:
            for i in range(5):
                tg.start_soon(worker, f"worker.{i}", i)

        # Each worker should have had its own context
        assert len(results) == 5

        # All contexts should be unique
        context_ids = [result[1] for result in results]
        assert len(set(context_ids)) == 5

    @patch("pymidil.event.context.uuid4")
    async def test_event_context_uuid_generation(self, mock_uuid4) -> None:
        """Test that event_context uses uuid4 for ID generation."""
        mock_uuid = type("MockUUID", (), {"hex": "mocked-uuid-hex"})()
        mock_uuid4.return_value = mock_uuid

        async with event_context("test.event") as ctx:
            assert ctx.id == "mocked-uuid-hex"

        mock_uuid4.assert_called_once()

    async def test_event_context_with_none_parent_override(self) -> None:
        """Test event_context with None as parent_override."""
        async with event_context("outer.event"):
            # Explicitly set parent to None
            async with event_context("inner.event", parent_override=None) as inner_ctx:
                assert inner_ctx.parent is None

    async def test_event_context_preserves_existing_parent_when_no_override(
        self,
    ) -> None:
        """Test that existing parent context is preserved when no override is provided."""
        # Set up an initial context manually
        initial_context = EventContext(id="initial", event_type="initial.event")
        token = _current_event_context.set(initial_context)

        try:
            async with event_context("new.event") as new_ctx:
                assert new_ctx.parent == initial_context
        finally:
            _current_event_context.reset(token)

    async def test_event_context_type_annotations(self) -> None:
        """Test that event_context has proper type annotations."""
        async with event_context("typed.event") as ctx:
            # Should be EventContext type
            assert isinstance(ctx, EventContext)

            # Should have the expected attributes
            assert hasattr(ctx, "id")
            assert hasattr(ctx, "event_type")
            assert hasattr(ctx, "parent")

    async def test_event_context_with_empty_event_type(self) -> None:
        """Test event_context with empty event type."""
        async with event_context("") as ctx:
            assert ctx.event_type == ""
            assert isinstance(ctx.id, str)
            assert len(ctx.id) == 32  # uuid4().hex length
