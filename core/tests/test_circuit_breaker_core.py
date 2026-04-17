import asyncio
import time
import pytest
import threading
from framework.utils.circuit_breaker import CircuitBreaker, CircuitState, CircuitOpenError

def test_circuit_breaker_closed_to_open():
    """Test that the circuit breaker trips after the failure threshold is reached."""
    # Using 3 failures for a bit more buffer
    breaker = CircuitBreaker(name="test", failure_threshold=3, expected_exceptions=(ValueError,))
    
    # Successes don't trip it
    breaker.call(lambda: "ok")
    assert breaker.state == CircuitState.CLOSED
    assert breaker.to_dict()["failure_count"] == 0
    
    # First failure
    with pytest.raises(ValueError):
        breaker.call(lambda: raise_val_err())
    assert breaker.state == CircuitState.CLOSED
    assert breaker.to_dict()["failure_count"] == 1
    
    # Second failure
    with pytest.raises(ValueError):
        breaker.call(lambda: raise_val_err())
    assert breaker.state == CircuitState.CLOSED
    
    # Third failure -> Trips
    with pytest.raises(ValueError):
        breaker.call(lambda: raise_val_err())
    assert breaker.state == CircuitState.OPEN
    assert breaker.to_dict()["total_trips"] == 1

def raise_val_err():
    raise ValueError("fail")

def test_circuit_breaker_ignored_exceptions():
    """Test that non-monitored exceptions do not trip the breaker."""
    breaker = CircuitBreaker(name="test", failure_threshold=2, expected_exceptions=(ValueError,))
    
    # KeyError is not in expected_exceptions, so it should be treated as a successful pass-through
    # for circuit state purposes (server is answering, even if with an application error)
    for _ in range(5):
        with pytest.raises(KeyError):
            breaker.call(lambda: raise_key_err())
    
    assert breaker.state == CircuitState.CLOSED
    assert breaker.to_dict()["failure_count"] == 0

def raise_key_err():
    raise KeyError("ignore me")

def test_circuit_breaker_recovery_half_open():
    """Test the transition from OPEN to HALF_OPEN after timeout."""
    breaker = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.1, expected_exceptions=(ValueError,))
    
    # Trip it
    with pytest.raises(ValueError):
        breaker.call(lambda: raise_val_err())
    assert breaker.state == CircuitState.OPEN
    
    # Calls while OPEN should fail fast
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: "blocked")
        
    # Wait for recovery
    time.sleep(0.15)
    assert breaker.state == CircuitState.HALF_OPEN

def test_circuit_breaker_atomic_probe():
    """Test that only one request is allowed in HALF_OPEN (thundering herd prevention)."""
    breaker = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.1, expected_exceptions=(ValueError,))
    
    # Trip it
    with pytest.raises(ValueError):
        breaker.call(lambda: raise_val_err())
    
    time.sleep(0.15)
    assert breaker.state == CircuitState.HALF_OPEN
    
    # Start a probe that takes time
    def slow_success():
        time.sleep(0.2)
        return "recovered"
    
    results = []
    def call_breaker():
        try:
            results.append(breaker.call(slow_success))
        except Exception as e:
            results.append(e)

    t1 = threading.Thread(target=call_breaker)
    t1.start()
    
    time.sleep(0.05) # Ensure t1 has acquired the probe
    
    # Second call should fail immediately with CircuitOpenError (thundering herd)
    with pytest.raises(CircuitOpenError) as excinfo:
        breaker.call(lambda: "too fast")
    assert "Blocking thundering herd" in str(excinfo.value)
    assert breaker.to_dict()["total_herd_rejections"] > 0
    
    t1.join()
    assert results[0] == "recovered"
    assert breaker.state == CircuitState.CLOSED

@pytest.mark.asyncio
async def test_circuit_breaker_async():
    """Test async call support."""
    breaker = CircuitBreaker(name="async-test", failure_threshold=1, expected_exceptions=(ValueError,))
    
    async def async_fail():
        await asyncio.sleep(0.01)
        raise ValueError("async fail")
        
    with pytest.raises(ValueError):
        await breaker.acall(async_fail)
    
    assert breaker.state == CircuitState.OPEN

def test_circuit_breaker_telemetry_to_dict():
    """Test that to_dict includes all relevant metrics."""
    breaker = CircuitBreaker(name="metrics-test", failure_threshold=5)
    d = breaker.to_dict()
    
    expected_keys = {
        "name", "state", "failure_count", "total_successes", 
        "total_failures", "total_trips", "total_herd_rejections", 
        "probe_in_progress"
    }
    assert expected_keys.issubset(set(d.keys()))
    assert d["name"] == "metrics-test"
