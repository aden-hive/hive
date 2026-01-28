from io import StringIO
import os.path

from jeepney.low_level import MessageType, HeaderFields
from jeepney.bindgen import code_from_xml

sample_file = os.path.join(os.path.dirname(__file__), 'secrets_introspect.xml')

def test_bindgen():
    with open(sample_file) as f:
        xml = f.read()
    sio = StringIO()
    n_interfaces = code_from_xml(xml, path='/org/freedesktop/secrets',
                                 bus_name='org.freedesktop.secrets',
                                 fh=sio)
    # 5 interfaces defined, but we ignore Properties, Introspectable, Peer
    assert n_interfaces == 2

    # Run the generated code, defining the message generator classes.
    binding_ns = {}
    exec(sio.getvalue(), binding_ns)
    Service = binding_ns['Service']

    # Check basic functionality of the Service class
    assert Service.interface == 'org.freedesktop.Secret.Service'
    msg = Service().SearchItems({"service": "foo", "user": "bar"})
    assert msg.header.message_type is MessageType.method_call
    assert msg.header.fields[HeaderFields.destination] == 'org.freedesktop.secrets'
