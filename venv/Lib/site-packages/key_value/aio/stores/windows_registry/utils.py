import contextlib
import winreg

from key_value.shared.errors.store import StoreSetupError

HiveType = int


def get_reg_sz_value(hive: HiveType, sub_key: str, value_name: str) -> str | None:
    try:
        with winreg.OpenKey(key=hive, sub_key=sub_key) as reg_key:
            string, _ = winreg.QueryValueEx(reg_key, value_name)
            return string
    except (FileNotFoundError, OSError):
        return None


def set_reg_sz_value(hive: HiveType, sub_key: str, value_name: str, value: str) -> None:
    try:
        with winreg.OpenKey(key=hive, sub_key=sub_key, access=winreg.KEY_WRITE) as reg_key:
            winreg.SetValueEx(reg_key, value_name, 0, winreg.REG_SZ, value)
    except FileNotFoundError as e:
        msg = f"Registry key '{sub_key}' does not exist"
        raise StoreSetupError(msg) from e
    except OSError as e:
        msg = f"Failed to set registry value '{value_name}' at '{sub_key}'"
        raise StoreSetupError(msg) from e


def delete_reg_sz_value(hive: HiveType, sub_key: str, value_name: str) -> bool:
    try:
        with winreg.OpenKey(key=hive, sub_key=sub_key, access=winreg.KEY_WRITE) as reg_key:
            winreg.DeleteValue(reg_key, value_name)
            return True
    except (FileNotFoundError, OSError):
        return False


def has_key(hive: HiveType, sub_key: str) -> bool:
    try:
        with winreg.OpenKey(key=hive, sub_key=sub_key):
            return True
    except (FileNotFoundError, OSError):
        return False


def create_key(hive: HiveType, sub_key: str) -> None:
    try:
        key = winreg.CreateKey(hive, sub_key)
        key.Close()
    except OSError as e:
        msg = f"Failed to create registry key '{sub_key}'"
        raise StoreSetupError(msg) from e


def delete_key(hive: HiveType, sub_key: str) -> bool:
    try:
        winreg.DeleteKey(hive, sub_key)
    except (FileNotFoundError, OSError):
        return False
    else:
        return True


def delete_sub_keys(hive: HiveType, sub_key: str) -> None:
    try:
        with winreg.OpenKey(key=hive, sub_key=sub_key, access=winreg.KEY_WRITE | winreg.KEY_ENUMERATE_SUB_KEYS) as reg_key:
            while True:
                try:
                    # Always enumerate at index 0 since keys shift after deletion
                    next_child_key = winreg.EnumKey(reg_key, 0)
                except OSError:
                    # No more subkeys
                    break

                # Key already deleted or can't be deleted, skip it
                with contextlib.suppress(FileNotFoundError, OSError):
                    winreg.DeleteKey(reg_key, next_child_key)
    except (FileNotFoundError, OSError):
        return
