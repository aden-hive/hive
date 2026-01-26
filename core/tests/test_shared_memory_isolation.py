"""
Tests for SharedMemory data isolation (deep copy protection).

This test suite verifies that read operations return isolated copies,
preventing accidental mutations of shared state by read-only nodes.

Related Issue: Data integrity - shallow copy vulnerability
"""

import pytest
from framework.graph.node import SharedMemory


class TestSharedMemoryReadIsolation:
    """Test that read() returns isolated copies."""
    
    def test_read_list_isolation(self):
        """Read-only access should not allow mutation of lists."""
        # Setup: Node A writes a list
        memory = SharedMemory()
        original_list = [{"name": "Alice"}, {"name": "Bob"}]
        memory.write("users", original_list)
        
        # Action: Node B reads the list (read-only access)
        read_data = memory.read("users")
        
        # Attempt: Node B modifies the list
        read_data.append({"name": "Charlie"})
        read_data[0]["name"] = "Alicia"
        
        # Verify: Original data is unaffected
        assert memory.read("users") == [
            {"name": "Alice"}, 
            {"name": "Bob"}
        ]
    
    def test_read_dict_isolation(self):
        """Read-only access should not allow mutation of nested dicts."""
        # Setup: Node A writes a dict with nested structure
        memory = SharedMemory()
        original_data = {
            "config": {"timeout": 30, "retries": 3},
            "status": "active"
        }
        memory.write("settings", original_data)
        
        # Action: Node B reads the dict
        read_data = memory.read("settings")
        
        # Attempt: Node B modifies nested dict
        read_data["config"]["timeout"] = 60
        read_data["status"] = "inactive"
        
        # Verify: Original data is unaffected
        original = memory.read("settings")
        assert original["config"]["timeout"] == 30
        assert original["status"] == "active"
    
    def test_read_complex_nested_structure(self):
        """Read-only access should protect deeply nested structures."""
        # Setup: Complex nested data
        memory = SharedMemory()
        original_data = {
            "users": [
                {
                    "id": 1,
                    "name": "Alice",
                    "permissions": ["read", "write"],
                    "metadata": {"created": "2024-01-01", "active": True}
                },
                {
                    "id": 2,
                    "name": "Bob",
                    "permissions": ["read"],
                    "metadata": {"created": "2024-01-02", "active": False}
                }
            ]
        }
        memory.write("data", original_data)
        
        # Action: Read and attempt to modify at all levels
        read_data = memory.read("data")
        read_data["users"].append({"id": 3, "name": "Charlie"})
        read_data["users"][0]["name"] = "Alicia"
        read_data["users"][0]["permissions"][0] = "admin"
        read_data["users"][0]["metadata"]["active"] = False
        
        # Verify: Original is pristine
        original = memory.read("data")
        assert len(original["users"]) == 2
        assert original["users"][0]["name"] == "Alice"
        assert original["users"][0]["permissions"] == ["read", "write"]
        assert original["users"][0]["metadata"]["active"] == True
    
    def test_read_none_value(self):
        """Reading non-existent key should return None without error."""
        memory = SharedMemory()
        result = memory.read("nonexistent")
        assert result is None
    
    def test_read_primitive_types(self):
        """Primitive types should be returned safely (no mutation possible)."""
        memory = SharedMemory()
        memory.write("count", 42)
        memory.write("message", "hello")
        
        # Read primitives
        count = memory.read("count")
        message = memory.read("message")
        
        # Primitives are immutable, so this doesn't affect shared memory
        count = 100
        message = "goodbye"
        
        # Original values should be unchanged
        assert memory.read("count") == 42
        assert memory.read("message") == "hello"


class TestSharedMemoryReadAllIsolation:
    """Test that read_all() returns isolated copies of all accessible data."""
    
    def test_read_all_list_isolation(self):
        """read_all() should isolate list values."""
        memory = SharedMemory()
        memory.write("users", [{"name": "Alice"}])
        memory.write("count", 1)
        
        # Read all data
        all_data = memory.read_all()
        
        # Attempt to modify
        all_data["users"].append({"name": "Bob"})
        all_data["count"] = 2
        
        # Verify isolation
        assert memory.read_all()["users"] == [{"name": "Alice"}]
        assert memory.read_all()["count"] == 1
    
    def test_read_all_dict_isolation(self):
        """read_all() should isolate dict values."""
        memory = SharedMemory()
        original = {"config": {"timeout": 30}}
        memory.write("settings", original)
        
        all_data = memory.read_all()
        all_data["settings"]["config"]["timeout"] = 60
        
        # Original should be unchanged
        assert memory.read_all()["settings"]["config"]["timeout"] == 30
    
    def test_read_all_respects_read_permissions(self):
        """read_all() should only return permitted keys."""
        memory = SharedMemory()
        memory.write("public", "visible")
        memory.write("private", "secret")
        memory.write("sensitive", "confidential")
        
        # Create restricted view
        restricted = memory.with_permissions(
            read_keys=["public", "private"],
            write_keys=[]
        )
        
        # read_all() should only return permitted keys
        all_data = restricted.read_all()
        assert "public" in all_data
        assert "private" in all_data
        assert "sensitive" not in all_data
    
    def test_read_all_empty_memory(self):
        """read_all() on empty memory should return empty dict."""
        memory = SharedMemory()
        result = memory.read_all()
        assert result == {}


class TestShallowCopyOption:
    """Test the shallow=True performance optimization."""
    
    def test_read_shallow_for_primitive(self):
        """shallow=True should work fine for primitives."""
        memory = SharedMemory()
        memory.write("value", 42)
        
        result = memory.read("value", shallow=True)
        assert result == 42
    
    def test_read_shallow_still_isolates_dict(self):
        """shallow=True should still provide dict isolation."""
        memory = SharedMemory()
        memory.write("config", {"timeout": 30})
        
        # Read with shallow=True
        result = memory.read("config", shallow=True)
        result["timeout"] = 60
        
        # Original dict object should be different
        assert memory.read("config")["timeout"] == 30
    
    def test_read_shallow_does_not_isolate_nested_lists(self):
        """
        shallow=True should NOT isolate nested lists.
        This is documented behavior - caller must guarantee no mutation.
        """
        memory = SharedMemory()
        original_list = [1, 2, 3]
        memory.write("items", [original_list])
        
        # Read with shallow=True - nested list is NOT isolated
        result = memory.read("items", shallow=True)
        result[0].append(4)  # This WILL affect original
        
        # This documents the tradeoff - caller must be careful
        assert memory.read("items")[0] == [1, 2, 3, 4]
    
    def test_read_all_shallow(self):
        """read_all(shallow=True) should work but with caveats."""
        memory = SharedMemory()
        memory.write("list", [1, 2, 3])
        memory.write("string", "hello")
        
        # Shallow copy of the dict itself is provided
        result = memory.read_all(shallow=True)
        
        # Dict structure is isolated
        result["new_key"] = "value"
        assert "new_key" not in memory.read_all()
        
        # But list inside is NOT fully isolated with shallow=True
        result["list"].append(4)
        # This is expected with shallow=True
        assert memory.read("list")[-1] == 4  # Original was modified


class TestSharedMemoryDataIntegrity:
    """Test the overall data integrity guarantees of SharedMemory."""
    
    def test_multiple_readers_cant_corrupt_shared_state(self):
        """Multiple read-only nodes should not interfere with each other."""
        memory = SharedMemory()
        original_data = {
            "node_a_count": 0,
            "node_b_count": 0,
            "shared_list": [1, 2, 3]
        }
        memory.write("state", original_data)
        
        # Node A reads and attempts to modify
        state_a = memory.read("state")
        state_a["node_a_count"] = 100
        state_a["shared_list"].append(4)
        
        # Node B reads and attempts to modify
        state_b = memory.read("state")
        state_b["node_b_count"] = 200
        state_b["shared_list"].append(5)
        
        # Verify original is untouched by both
        final_state = memory.read("state")
        assert final_state["node_a_count"] == 0
        assert final_state["node_b_count"] == 0
        assert final_state["shared_list"] == [1, 2, 3]
    
    def test_read_permission_enforcement(self):
        """Permission checks should still work with deep copy."""
        memory = SharedMemory()
        memory.write("allowed_key", "value")
        memory.write("forbidden_key", "secret")
        
        # Create restricted view
        restricted = memory.with_permissions(
            read_keys=["allowed_key"],
            write_keys=[]
        )
        
        # Can read allowed
        assert restricted.read("allowed_key") == "value"
        
        # Cannot read forbidden
        with pytest.raises(PermissionError):
            restricted.read("forbidden_key")
    
    def test_concurrent_read_write_safety(self):
        """
        Simulate concurrent operations: Node A reading while Node B writes.
        Deep copy ensures Node A's read is not affected by Node B's write.
        """
        memory = SharedMemory()
        memory.write("data", [1, 2, 3])
        
        # Node A reads
        node_a_data = memory.read("data")
        
        # Node B writes new data
        memory.write("data", [10, 20, 30])
        
        # Node A's data should still be the original
        assert node_a_data == [1, 2, 3]
        
        # Current state should be Node B's write
        assert memory.read("data") == [10, 20, 30]


class TestBackwardCompatibility:
    """Ensure changes don't break existing code."""
    
    def test_read_returns_value_not_none(self):
        """read() should return the actual value, not None."""
        memory = SharedMemory()
        memory.write("test", {"key": "value"})
        
        result = memory.read("test")
        assert result is not None
        assert isinstance(result, dict)
        assert result["key"] == "value"
    
    def test_read_all_returns_dict_with_values(self):
        """read_all() should return proper dict with all values."""
        memory = SharedMemory()
        memory.write("key1", "value1")
        memory.write("key2", "value2")
        
        result = memory.read_all()
        assert isinstance(result, dict)
        assert len(result) == 2
        assert result["key1"] == "value1"
        assert result["key2"] == "value2"
    
    def test_write_and_read_cycle(self):
        """Basic write-read cycle should work as before."""
        memory = SharedMemory()
        
        # Write and read simple values
        memory.write("name", "Alice")
        assert memory.read("name") == "Alice"
        
        # Write and read complex objects
        memory.write("config", {"timeout": 30, "retries": 3})
        config = memory.read("config")
        assert config["timeout"] == 30
        assert config["retries"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
