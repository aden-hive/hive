from jeepney import DBusAddress, new_signal, new_method_call
from jeepney.bus_messages import MatchRule, message_bus

portal = DBusAddress(
    object_path='/org/freedesktop/portal/desktop',
    bus_name='org.freedesktop.portal.Desktop',
)
portal_req_iface = portal.with_interface('org.freedesktop.portal.Request')


def test_match_rule_simple():
    rule = MatchRule(
        type='signal', interface='org.freedesktop.portal.Request',
    )
    assert rule.matches(new_signal(portal_req_iface, 'Response'))

    # Wrong message type
    assert not rule.matches(new_method_call(portal_req_iface, 'Boo'))

    # Wrong interface
    assert not rule.matches(new_signal(
        portal.with_interface('org.freedesktop.portal.FileChooser'), 'Response'
    ))


def test_match_rule_path_namespace():
    assert MatchRule(path_namespace='/org/freedesktop/portal').matches(
        new_signal(portal_req_iface, 'Response')
    )
    assert "/freedesktop/" in (
        MatchRule(path_namespace='/org/freedesktop/portal').serialise()
    )

    # Prefix but not a parent in the path hierarchy
    assert not MatchRule(path_namespace='/org/freedesktop/por').matches(
        new_signal(portal_req_iface, 'Response')
    )


def test_match_rule_arg():
    rule = MatchRule(type='method_call')
    rule.add_arg_condition(0, 'foo')

    assert rule.matches(new_method_call(
        portal_req_iface, 'Boo', signature='s', body=('foo',)
    ))

    assert not rule.matches(new_method_call(
        portal_req_iface, 'Boo', signature='s', body=('foobar',)
    ))

    # No such argument
    assert not rule.matches(new_method_call(portal_req_iface, 'Boo'))


def test_match_rule_arg_path():
    rule = MatchRule(type='method_call')
    rule.add_arg_condition(0, '/aa/bb/', kind='path')

    # Exact match
    assert rule.matches(new_method_call(
        portal_req_iface, 'Boo', signature='s', body=('/aa/bb/',)
    ))

    # Match a prefix
    assert rule.matches(new_method_call(
        portal_req_iface, 'Boo', signature='s', body=('/aa/bb/cc',)
    ))

    # Argument is a prefix, ending with /
    assert rule.matches(new_method_call(
        portal_req_iface, 'Boo', signature='s', body=('/aa/',)
    ))

    # Argument is a prefix, but NOT ending with /
    assert not rule.matches(new_method_call(
        portal_req_iface, 'Boo', signature='s', body=('/aa',)
    ))

    assert not rule.matches(new_method_call(
        portal_req_iface, 'Boo', signature='s', body=('/aa/bb',)
    ))

    # Not a string
    assert not rule.matches(new_method_call(
        portal_req_iface, 'Boo', signature='u', body=(12,)
    ))


def test_match_rule_arg_namespace():
    rule = MatchRule(member='NameOwnerChanged')
    rule.add_arg_condition(0, 'com.example.backend1', kind='namespace')

    # Exact match
    assert rule.matches(new_signal(
        message_bus, 'NameOwnerChanged', 's', ('com.example.backend1',)
    ))

    # Parent of the name
    assert rule.matches(new_signal(
        message_bus, 'NameOwnerChanged', 's', ('com.example.backend1.foo.bar',)
    ))

    # Prefix but not a parent in the namespace
    assert not rule.matches(new_signal(
        message_bus, 'NameOwnerChanged', 's', ('com.example.backend12',)
    ))

    # Not a string
    assert not rule.matches(new_signal(
        message_bus, 'NameOwnerChanged', 'u', (1,)
    ))
