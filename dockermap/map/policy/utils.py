# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from docker.utils import compare_version
import six

from ...functional import resolve_value
from ..config import get_host_path
from ..input import is_path


INITIAL_START_TIME = '0001-01-01T00:00:00Z'


def extract_user(user_value):
    """
    Extract the user for running a container from the following possible input formats:

    * Integer (UID)
    * User name string
    * Tuple of ``user, group``
    * String in the format ``user:group``

    :param user_value: User name, uid, user-group tuple, or user:group string.
    :type user_value: int or tuple or unicode
    :return: User name or id.
    :rtype: unicode
    """
    user = resolve_value(user_value)
    if not user and user != 0 and user != '0':
        return None
    if isinstance(user, tuple):
        return user[0]
    if isinstance(user, int):
        return six.text_type(user)
    return user.partition(':')[0]


def update_kwargs(kwargs, *updates):
    """
    Utility function for merging multiple keyword arguments, depending on their type:

    * Non-existent keys are added.
    * Existing lists or tuples are extended.
      The keywords ``command`` and ``entrypoint`` are however simply overwritten.
    * Nested dictionaries are updated, overriding previous key-value assignments.
    * Other items are simply overwritten (just like in a regular dictionary update) unless the updating value is
      ``None``.

    Lists/tuples and dictionaries are (shallow-)copied before adding and late resolving values are looked up.
    This function does not recurse.

    :param kwargs: Base keyword arguments.
    :type kwargs: dict
    :param updates: Dictionaries to update ``kwargs`` with.
    :type updates: tuple[dict]
    :return: A merged dictionary of keyword arguments.
    :rtype: dict
    """
    for update in updates:
        if not update:
            continue
        for key, val in six.iteritems(update):
            u_item = resolve_value(val)
            if u_item is None:
                continue
            if key in ('command' or 'entrypoint'):
                kwargs[key] = u_item
            elif isinstance(u_item, (tuple, list)):
                kw_item = kwargs.get(key)
                u_list = map(resolve_value, u_item)
                if isinstance(kw_item, list):
                    kw_item.extend(u_list)
                elif isinstance(kw_item, tuple):
                    new_list = list(kw_item)
                    new_list.extend(u_list)
                    kwargs[key] = new_list
                else:
                    kwargs[key] = list(u_list)
            elif isinstance(u_item, dict):
                kw_item = kwargs.get(key)
                u_dict = {u_k: resolve_value(u_v) for u_k, u_v in six.iteritems(u_item)}
                if isinstance(kw_item, dict):
                    kw_item.update(u_dict)
                else:
                    kwargs[key] = u_dict
            else:
                kwargs[key] = u_item


def init_options(options):
    """
    Initialize ``create_options`` or  ``start_options`` of a container configuration. If ``options`` is a callable, it
    is run to initialize the values, otherwise it simply returns ``options`` or an empty dictionary.

    :param options: Options as a dictionary.
    :type options: callable or dict
    :return: Initial keyword arguments.
    :rtype: dict
    """
    if options:
        if callable(options):
            return options()
        return options.copy()
    return {}


def get_shared_volume_path(container_map, volume, instance=None):
    """
    Resolves a volume alias of a container configuration or a tuple of two paths to the host and container paths.

    :param container_map: Container map.
    :type container_map: dockermap.map.container.ContainerMap
    :param volume: Volume alias or tuple of paths.
    :type volume: unicode | AbstractLazyObject | tuple[unicode] | tuple[AbstractLazyObject]
    :param instance: Optional instance name.
    :type instance: unicode
    :return: Tuple of host path and container bind path.
    :rtype: tuple[unicode]
    """
    if isinstance(volume, tuple):
        v_len = len(volume)
        if v_len == 2:
            c_path = resolve_value(volume[0])
            if is_path(c_path):
                return c_path, get_host_path(container_map.host.root, volume[1], instance)
        raise ValueError("Host-container-binding must be described by two paths or one alias name. "
                         "Found {0}.".format(volume))
    c_path = resolve_value(container_map.volumes.get(volume))
    h_path = container_map.host.get(volume, instance)
    if c_path:
        return c_path, h_path
    raise KeyError("No host-volume information found for alias {0}.".format(volume))


def get_environment(container_map, container_config):
    """
    generates an environment variable list for the container

    :param container_map: Container map.
    :type container_map: dockermap.map.container.ContainerMap
    :return: list of environment variables in the 'key=val' format
    """
    return_val = []
    val_dict = container_config.environment
    if isinstance(val_dict, dict):
        # in the dictiorary format
        for k,v in val_dict.iteritems():
            return_val.append("{0}={1}".format(k,v))
    elif isinstance(val_dict, list):
        return_val = val_dict

    return return_val

def get_volumes(container_map, config):
    """
    Generates volume paths for the ``volumes`` argument during container creation.

    :param container_map: Container map.
    :type container_map: dockermap.map.container.ContainerMap
    :param config: Container configuration.
    :type config: dockermap.map.config.ContainerConfiguration
    :return: List of shared volume mount points.
    :rtype: list[unicode]
    """
    def _volume_path(vol):
        if isinstance(vol, tuple) and len(vol) == 2:
            return resolve_value(vol[0])
        v_path = resolve_value(container_map.volumes.get(vol))
        if v_path:
            return v_path
        raise KeyError("No host-volume information found for alias {0}.".format(vol))

    volumes = [resolve_value(s) for s in config.shares]
    volumes.extend([_volume_path(b.volume) for b in config.binds])
    return volumes


def get_host_binds(container_map, config, instance):
    """
    Generates the dictionary entries of host volumes of a container configuration.

    :param container_map: Container map.
    :type container_map: dockermap.map.container.ContainerMap
    :param config: Container configuration.
    :type config: dockermap.map.config.ContainerConfiguration
    :param instance: Instance name. Pass ``None`` if not applicable.
    :type instance: unicode
    :return: Dictionary of shared volumes with host volumes and the read-only flag.
    :rtype: dict[unicode, dict]
    """
    host_binds = {}
    for shared_volume in config.binds:
        volume = shared_volume.volume
        c_path, h_path = get_shared_volume_path(container_map, volume, instance)
        host_binds[h_path] = dict(bind=c_path, ro=shared_volume.readonly)

    return host_binds


def get_port_bindings(container_config, client_config):
    """
    Generates the input dictionary contents for the ``port_bindings`` argument.

    :param container_config: Container configuration.
    :type container_config: dockermap.map.config.ContainerConfiguration
    :param client_config: Client configuration.
    :type client_config: dockermap.map.config.ClientConfiguration
    :return: Dictionary of ports with mapped port, and if applicable, with bind address
    :rtype: dict[unicode, unicode | int | tuple]
    """
    port_bindings = {}
    for port_binding in container_config.exposes:
        exposed_port = resolve_value(port_binding.exposed_port)
        bind_port = resolve_value(port_binding.host_port)
        interface = resolve_value(port_binding.interface)
        if interface and bind_port:
            bind_addr = resolve_value(client_config.interfaces.get(interface))
            if not bind_addr:
                raise ValueError("Address for interface '{0}' not found in client configuration.".format(interface))
            port_bindings[exposed_port] = (bind_addr, bind_port)
        elif bind_port:
            port_bindings[exposed_port] = bind_port
    return port_bindings


def is_initial(container_state):
    """
    Checks if a container with the given status information has ever been started.

    :param container_state: Container status dictionary.
    :type container_state: dict
    :return: ``True`` if the container has never been started before, ``False`` otherwise.
    :rtype: bool
    """
    return container_state['StartedAt'] == INITIAL_START_TIME


def use_host_config(client):
    """
    Checks whether the client should pass the HostConfig options when creating containers, or use the older behavior
    of passing the keyword arguments to the start method of the client.

    :param client: Client object.
    :type client: docker.client.Client
    :return: ``True`` if the newer behavior should be used.
    :rtype: bool
    """
    return compare_version('1.15', client.api_version) >= 0
