# Browser-Use Patterns Analysis

## Key Learnings from `/home/timothy/aden/browser-use`

### 1. Element Click Implementation

**browser-use approach** (`browser_use/actor/element.py`):

```python
# Three fallback methods for element geometry:

# Method 1: DOM.getContentQuads (best for inline elements and complex layouts)
content_quads_result = await self._client.send.DOM.getContentQuads(
    params={'backendNodeId': self._backend_node_id}, session_id=self._session_id
)

# Method 2: DOM.getBoxModel (fallback)
box_model = await self._client.send.DOM.getBoxModel(
    params={'backendNodeId': self._backend_node_id}, session_id=self._session_id
)

# Method 3: JavaScript getBoundingClientRect (final fallback)
bounds_result = await self._client.send.Runtime.callFunctionOn(
    params={
        'functionDeclaration': """
            function() {
                const rect = this.getBoundingClientRect();
                return {
                    x: rect.left,
                    y: rect.top,
                    width: rect.width,
                    height: rect.height
                };
            }
        """,
        'objectId': object_id,
        'returnByValue': True,
    },
    session_id=self._session_id,
)

# Method 4: JavaScript click (if all else fails)
await self._client.send.Runtime.callFunctionOn(
    params={
        'functionDeclaration': 'function() { this.click(); }',
        'objectId': object_id,
    },
    session_id=self._session_id,
)
```

**Key differences from our implementation:**
- Uses `backendNodeId` instead of `nodeId` (more stable across DOM updates)
- Tries `DOM.getContentQuads` first (better for complex layouts)
- Multiple fallback methods with JavaScript click as final resort
- Finds largest visible quad within viewport
- Has timeouts for each mouse operation
- Proper modifier key handling

### 2. Input/Type Text Implementation

**browser-use approach**:

```python
# 1. Scroll element into view
await cdp_client.send.DOM.scrollIntoViewIfNeeded(
    params={'backendNodeId': backend_node_id}, 
    session_id=session_id
)

# 2. Get object ID
result = await cdp_client.send.DOM.resolveNode(
    params={'backendNodeId': backend_node_id},
    session_id=session_id,
)
object_id = result['object']['objectId']

# 3. Focus via JavaScript (more reliable than CDP focus)
await cdp_client.send.Runtime.callFunctionOn(
    params={
        'functionDeclaration': 'function() { this.focus(); }',
        'objectId': object_id,
    },
    session_id=session_id,
)

# 4. Type using Input.dispatchKeyEvent
for char in text:
    await self._client.send.Input.dispatchKeyEvent(
        params={
            'type': 'keyDown',
            'key': char,
            'text': char,
        },
        session_id=self._session_id,
    )
```

### 3. Accessibility Tree (Snapshot)

**browser-use approach** (`browser_use/dom/service.py`):

- Uses `Accessibility.getFullAXTree` for accessibility data
- Combines with DOM tree for enhanced snapshot
- Filters by paint order (elements actually visible)
- Handles iframes with depth limits
- Detects hidden interactive elements and reports them
- Uses `DOM.getFrameOwner` for iframe handling

### 4. CDP Domain Handling

**browser-use approach** (`browser_use/browser/session.py`):

```python
# Session setup enables ONLY these domains:
await self._client.send.Page.enable(session_id=self._session_id)
await self._client.send.DOM.enable(session_id=self._session_id)
await self._client.send.Runtime.enable(session_id=self._session_id)
await self._client.send.Network.enable(session_id=self._session_id)

# Input.enable is NEVER called - it's not required!
```

### 5. Element Selection

**browser-use approach**:

- Uses index-based element selection from accessibility tree
- Maintains a map of index -> EnhancedAXNode
- Elements have `backendNodeId` which is stable
- Uses `DOM.pushNodesByBackendIdsToFrontend` to get fresh nodeId

### 6. Scroll Handling

**browser-use approach**:

```python
# Uses multiple methods:
# 1. DOM.scrollIntoViewIfNeeded (CDP)
# 2. JavaScript scrollIntoView as fallback
# 3. Mouse wheel events for smooth scrolling
```

### 7. Wait Strategies

**browser-use approach**:

- `wait_for_element` uses CDP DOM queries with polling
- Has configurable timeouts
- Uses `DOM.getContentQuads` to verify element is visible
- Detects page load state via `Page.loadEventFired`

---

## Improvements to Make to hive/tools

### 1. Bridge Updates

- [x] Use `backendNodeId` instead of `nodeId` where possible
- [x] Add `DOM.getContentQuads` as primary method for element geometry
- [x] Add JavaScript click as final fallback
- [x] Add proper timeouts to mouse operations
- [x] Handle modifier keys for click

### 2. Type Text Updates

- [x] Focus element via JavaScript before typing
- [x] Use `Input.dispatchKeyEvent` for typing (more reliable than insertText)

### 3. Snapshot Updates

- [x] Use accessibility tree (CDP Accessibility domain)
- [x] Add computed styles to detect visibility
- [x] Report hidden interactive elements

### 4. Error Handling

- [x] Better error messages with element context
- [x] Graceful fallbacks instead of hard failures
- [x] Timeout handling for all CDP operations
