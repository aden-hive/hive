"""Method decorator helpers."""

__all__ = ()

import functools
import warnings
import weakref


def _warn_classmethod(stacklevel):
    warnings.warn(
        "decorating class methods with @cachedmethod is deprecated",
        DeprecationWarning,
        stacklevel=stacklevel,
    )


def _warn_instance_dict(msg, stacklevel):
    warnings.warn(
        msg,
        DeprecationWarning,
        stacklevel=stacklevel,
    )


def _none(_):
    return None


class _WrapperBase:
    """Wrapper base class providing default implementations for properties."""

    def __init__(self, obj, method, cache, key, lock=None, cond=None):
        if isinstance(obj, type):
            _warn_classmethod(stacklevel=5)
        functools.update_wrapper(self, method)
        self._obj = obj  # protected
        self.__cache = cache
        self.__key = functools.partial(key, obj)
        self.__lock = lock if lock is not None else _none
        self.__cond = cond if cond is not None else _none

    def __call__(self, *args, **kwargs):
        raise NotImplementedError()  # pragma: no cover

    def cache_clear(self):
        raise NotImplementedError()  # pragma: no cover

    @property
    def cache(self):
        return self.__cache(self._obj)

    @property
    def cache_key(self):
        return self.__key  # self._obj passed via functools.partial

    @property
    def cache_lock(self):
        return self.__lock(self._obj)

    @property
    def cache_condition(self):
        return self.__cond(self._obj)


class _DescriptorBase:
    """Descriptor base class implementing the basic descriptor protocol."""

    def __init__(self, deprecated=False):
        self.__attrname = None
        self.__deprecated = deprecated

    def __set_name__(self, owner, name):
        if self.__attrname is None:
            self.__attrname = name
        elif name != self.__attrname:
            raise TypeError(
                "Cannot assign the same @cachedmethod to two different names "
                f"({self.__attrname!r} and {name!r})."
            )

    def __get__(self, obj, objtype=None):
        wrapper = self.Wrapper(obj)
        if obj is None:
            # Return the wrapper itself without modification when accessed
            # through the class to support class-level introspection, such
            # as for mocking with autospec=True in unittest.mock.
            pass
        elif self.__attrname is not None:
            # replace descriptor instance with wrapper in instance dict
            try:
                # In case of a race condition where another thread already replaced
                # the descriptor, prefer the initial wrapper.
                wrapper = obj.__dict__.setdefault(self.__attrname, wrapper)
            except AttributeError:
                # not all objects have __dict__ (e.g. class defines slots)
                msg = (
                    f"No '__dict__' attribute on {type(obj).__name__!r} "
                    f"instance to cache {self.__attrname!r} property."
                )
                if self.__deprecated:
                    _warn_instance_dict(msg, 3)
                else:
                    raise TypeError(msg) from None
            except TypeError:
                msg = (
                    f"The '__dict__' attribute on {type(obj).__name__!r} "
                    f"instance does not support item assignment for "
                    f"caching {self.__attrname!r} property."
                )
                if self.__deprecated:
                    _warn_instance_dict(msg, 3)
                else:
                    raise TypeError(msg) from None
        elif self.__deprecated:
            pass  # deprecated @classmethod, warning already raised elsewhere
        else:
            msg = "Cannot use @cachedmethod instance without calling __set_name__ on it"
            raise TypeError(msg) from None
        return wrapper


class _DeprecatedDescriptorBase(_DescriptorBase):
    """Descriptor base class supporting deprecated @classmethod use."""

    def __init__(self, wrapper, cache_clear):
        super().__init__(deprecated=True)
        self.__wrapper = wrapper
        self.__cache_clear = cache_clear

    # called for @classmethod with Python >= 3.13
    def __call__(self, *args, **kwargs):
        _warn_classmethod(stacklevel=3)
        return self.__wrapper(*args, **kwargs)

    # backward-compatible @classmethod handling with Python >= 3.13
    def cache_clear(self, objtype):
        _warn_classmethod(stacklevel=3)
        return self.__cache_clear(objtype)


# At least for now, the implementation prefers clarity and performance
# over ease of maintenance, thus providing separate descriptors for
# all valid combinations of decorator parameters lock, condition and
# info.


def _condition_info(method, cache, key, lock, cond, info):
    class Descriptor(_DescriptorBase):
        class Wrapper(_WrapperBase):
            def __init__(self, obj):
                super().__init__(obj, method, cache, key, lock, cond)
                self.__hits = self.__misses = 0
                self.__pending = set()

            def __call__(self, *args, **kwargs):
                cache = self.cache
                lock = self.cache_lock
                cond = self.cache_condition
                key = self.cache_key(*args, **kwargs)

                with lock:
                    cond.wait_for(lambda: key not in self.__pending)
                    try:
                        result = cache[key]
                        self.__hits += 1
                        return result
                    except KeyError:
                        self.__pending.add(key)
                        self.__misses += 1
                try:
                    val = method(self._obj, *args, **kwargs)
                    with lock:
                        try:
                            cache[key] = val
                        except ValueError:
                            pass  # value too large
                        return val
                finally:
                    with lock:
                        self.__pending.remove(key)
                        cond.notify_all()

            def cache_clear(self):
                with self.cache_lock:
                    self.cache.clear()
                    self.__hits = self.__misses = 0

            def cache_info(self):
                with self.cache_lock:
                    return info(self.cache, self.__hits, self.__misses)

    return Descriptor()


def _locked_info(method, cache, key, lock, info):
    class Descriptor(_DescriptorBase):
        class Wrapper(_WrapperBase):
            def __init__(self, obj):
                super().__init__(obj, method, cache, key, lock)
                self.__hits = self.__misses = 0

            def __call__(self, *args, **kwargs):
                cache = self.cache
                lock = self.cache_lock
                key = self.cache_key(*args, **kwargs)
                with lock:
                    try:
                        result = cache[key]
                        self.__hits += 1
                        return result
                    except KeyError:
                        self.__misses += 1
                val = method(self._obj, *args, **kwargs)
                with lock:
                    try:
                        # In case of a race condition, i.e. if another thread
                        # stored a value for this key while we were calling
                        # method(), prefer the cached value.
                        return cache.setdefault(key, val)
                    except ValueError:
                        return val  # value too large

            def cache_clear(self):
                with self.cache_lock:
                    self.cache.clear()
                    self.__hits = self.__misses = 0

            def cache_info(self):
                with self.cache_lock:
                    return info(self.cache, self.__hits, self.__misses)

    return Descriptor()


def _unlocked_info(method, cache, key, info):
    class Descriptor(_DescriptorBase):
        class Wrapper(_WrapperBase):
            def __init__(self, obj):
                super().__init__(obj, method, cache, key)
                self.__hits = self.__misses = 0

            def __call__(self, *args, **kwargs):
                cache = self.cache
                key = self.cache_key(*args, **kwargs)
                try:
                    result = cache[key]
                    self.__hits += 1
                    return result
                except KeyError:
                    self.__misses += 1
                val = method(self._obj, *args, **kwargs)
                try:
                    cache[key] = val
                except ValueError:
                    pass  # value too large
                return val

            def cache_clear(self):
                self.cache.clear()
                self.__hits = self.__misses = 0

            def cache_info(self):
                return info(self.cache, self.__hits, self.__misses)

    return Descriptor()


def _condition(method, cache, key, lock, cond):
    # backward-compatible weakref dictionary for Python >= 3.13
    pending = weakref.WeakKeyDictionary()

    def wrapper(self, pending, *args, **kwargs):
        c = cache(self)
        k = key(self, *args, **kwargs)
        with lock(self):
            cond(self).wait_for(lambda: k not in pending)
            try:
                return c[k]
            except KeyError:
                pending.add(k)
        try:
            v = method(self, *args, **kwargs)
            with lock(self):
                try:
                    c[k] = v
                except ValueError:
                    pass  # value too large
                return v
        finally:
            with lock(self):
                pending.remove(k)
                cond(self).notify_all()

    def cache_clear(self):
        c = cache(self)
        with lock(self):
            c.clear()

    def classmethod_wrapper(self, *args, **kwargs):
        p = pending.setdefault(self, set())
        return wrapper(self, p, *args, **kwargs)

    class Descriptor(_DeprecatedDescriptorBase):
        class Wrapper(_WrapperBase):
            def __init__(self, obj):
                super().__init__(obj, method, cache, key, lock, cond)
                self.__pending = set()

            def __call__(self, *args, **kwargs):
                return wrapper(self._obj, self.__pending, *args, **kwargs)

            # objtype: backward-compatible @classmethod handling with Python < 3.13
            def cache_clear(self, _objtype=None):
                return cache_clear(self._obj)

    return Descriptor(classmethod_wrapper, cache_clear)


def _locked(method, cache, key, lock):
    def wrapper(self, *args, **kwargs):
        c = cache(self)
        k = key(self, *args, **kwargs)
        with lock(self):
            try:
                return c[k]
            except KeyError:
                pass  # key not found
        v = method(self, *args, **kwargs)
        with lock(self):
            try:
                # In case of a race condition, i.e. if another thread
                # stored a value for this key while we were calling
                # method(), prefer the cached value.
                return c.setdefault(k, v)
            except ValueError:
                return v  # value too large

    def cache_clear(self):
        c = cache(self)
        with lock(self):
            c.clear()

    class Descriptor(_DeprecatedDescriptorBase):
        class Wrapper(_WrapperBase):
            def __init__(self, obj):
                super().__init__(obj, method, cache, key, lock)

            def __call__(self, *args, **kwargs):
                return wrapper(self._obj, *args, **kwargs)

            # objtype: backward-compatible @classmethod handling with Python < 3.13
            def cache_clear(self, _objtype=None):
                return cache_clear(self._obj)

    return Descriptor(wrapper, cache_clear)


def _unlocked(method, cache, key):
    def wrapper(self, *args, **kwargs):
        c = cache(self)
        k = key(self, *args, **kwargs)
        try:
            return c[k]
        except KeyError:
            pass  # key not found
        v = method(self, *args, **kwargs)
        try:
            c[k] = v
        except ValueError:
            pass  # value too large
        return v

    def cache_clear(self):
        c = cache(self)
        c.clear()

    class Descriptor(_DeprecatedDescriptorBase):
        class Wrapper(_WrapperBase):
            def __init__(self, obj):
                super().__init__(obj, method, cache, key)

            def __call__(self, *args, **kwargs):
                return wrapper(self._obj, *args, **kwargs)

            # objtype: backward-compatible @classmethod handling with Python < 3.13
            def cache_clear(self, _objtype=None):
                return cache_clear(self._obj)

    return Descriptor(wrapper, cache_clear)


def _wrapper(method, cache, key, lock=None, cond=None, info=None):
    if info is not None:
        if cond is not None and lock is not None:
            wrapper = _condition_info(method, cache, key, lock, cond, info)
        elif cond is not None:
            wrapper = _condition_info(method, cache, key, cond, cond, info)
        elif lock is not None:
            wrapper = _locked_info(method, cache, key, lock, info)
        else:
            wrapper = _unlocked_info(method, cache, key, info)
    else:
        if cond is not None and lock is not None:
            wrapper = _condition(method, cache, key, lock, cond)
        elif cond is not None:
            wrapper = _condition(method, cache, key, cond, cond)
        elif lock is not None:
            wrapper = _locked(method, cache, key, lock)
        else:
            wrapper = _unlocked(method, cache, key)

    # backward-compatible properties for deprecated @classmethod use
    wrapper.cache = cache
    wrapper.cache_key = key
    wrapper.cache_lock = lock if lock is not None else cond
    wrapper.cache_condition = cond

    return functools.update_wrapper(wrapper, method)
