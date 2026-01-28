import os

have_session_bus = bool(os.environ.get('DBUS_SESSION_BUS_ADDRESS'))
