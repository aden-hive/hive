# SecretStorage module for Python
# Access passwords using the SecretService DBus API
# Author: Dmitry Shachnev, 2013-2016
# License: 3-clause BSD, see LICENSE file

# This file contains some common defines.

SS_PREFIX = 'org.freedesktop.Secret.'
SS_PATH = '/org/freedesktop/secrets'

DBUS_UNKNOWN_METHOD = 'org.freedesktop.DBus.Error.UnknownMethod'
DBUS_ACCESS_DENIED = 'org.freedesktop.DBus.Error.AccessDenied'
DBUS_SERVICE_UNKNOWN = 'org.freedesktop.DBus.Error.ServiceUnknown'
DBUS_EXEC_FAILED = 'org.freedesktop.DBus.Error.Spawn.ExecFailed'
DBUS_NO_REPLY = 'org.freedesktop.DBus.Error.NoReply'
DBUS_NOT_SUPPORTED = 'org.freedesktop.DBus.Error.NotSupported'
DBUS_NO_SUCH_OBJECT = 'org.freedesktop.Secret.Error.NoSuchObject'
DBUS_UNKNOWN_OBJECT = 'org.freedesktop.DBus.Error.UnknownObject'

ALGORITHM_PLAIN = 'plain'
ALGORITHM_DH = 'dh-ietf1024-sha256-aes128-cbc-pkcs7'
