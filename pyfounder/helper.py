#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: set et ts=8 sts=4 sw=4 ai fenc=utf-8:

import os
import errno
import fnmatch
import math

import yaml
try:
        from yaml import CLoader as yaml_Loader, CDumper as yaml_Dumper
except ImportError:
        from yaml import Loader as yaml_Loader, Dumper as yaml_Dumper

import  jinja2.exceptions

class ConfigException(Exception):
    pass

def humanbytes(i, binary=False, precision=2):
    MULTIPLES = ["B", "k{}B", "M{}B", "G{}B", "T{}B", "P{}B", "E{}B", "Z{}B", "Y{}B"]
    base = 1024 if binary else 1000
    multiple = math.trunc(math.log2(i) / math.log2(base))
    value = i / math.pow(base, multiple)
    suffix = MULTIPLES[multiple].format("i" if binary else "")
    return "{value:.{precision}f} {suffix}".format(value=value,precision=precision,suffix=suffix)

def yaml_load(str):
    return yaml.load(str, Loader=yaml_Loader)

def yaml_dump(data):
    return yaml.dump(data, Dumper=yaml_Dumper)

def get_pxecfg_directory():
    from pyfounder.server import app
    p = app.config['PXECFG_DIRECTORY']
    if not len(p)>0:
        raise ConfigException("Not configured.".format(p))
    if not os.path.isdir(p):
        raise ConfigException("Directory {} not found.".format(p))
    if not os.access(p, os.W_OK):
        raise ConfigException("Directory {} is not writeable.".format(p))
    return p

def get_hosts_yaml():
    from pyfounder.server import app
    p = app.config['PYFOUNDER_HOSTS']
    if not len(p)>0:
        raise ConfigException("Not configured.".format(p))
    if not os.path.isfile(p):
        raise ConfigException("File {} not found.".format(p))
    if not os.access(p, os.R_OK):
        raise ConfigException("File {} is not readable.".format(p))
    return p

def get_template_directory():
    from pyfounder.server import app
    p = app.config['PYFOUNDER_TEMPLATES']
    if not len(p)>0:
        raise ConfigException("Not configured.".format(p))
    if not os.path.isdir(p):
        raise ConfigException("Directory {} not found.".format(p))
    return p

def load_hosts_yaml(filename=None):
    if filename is None:
        filename = get_hosts_yaml()
    try:
        with open(filename, 'r') as f:
            return yaml.load(f, Loader=yaml_Loader)
    except (IOError) as e:
        raise ConfigException("Unable to load {}: {}.".format(filename,e))
    except (yaml.MarkedYAMLError, yaml.YAMLError) as e:
        raise ConfigException("Unable to load {}: {}.".format(filename,e))

def load_hosts_config(filename=None):
    d = load_hosts_yaml(filename)
    hosts = {}
    if d is None or 'hosts' not in d or d['hosts'] is None:
        return {}
    for hostname, cfg in d['hosts'].items():
        # set host default values
        hc = {}
        if 'class' in cfg:
            if cfg['class'] in d['classes']:
                hc.update(d['classes'][cfg['class']])
        # FIXME use update()
        for key,value in cfg.items():
            hc[key] = value
        # that looks strange, but it necessary to get everything
        # in one place, when generating the templates
        hc['name'] = hostname
        hosts[hostname] = hc
    return hosts

def global_config(filename=None):
    d = load_hosts_yaml(filename)
    try: g = d['globals']
    except KeyError: g = {}
    if g is None: g = {}
    from pyfounder.server import app
    g.update({
        'pyfounder_ip' : app.config['PYFOUNDER_IP'],
        'pyfounder_url' : app.config['PYFOUNDER_URL'],
    })
    return g

def host_config(hostname, hosts=None):
    if hosts is None:
        hosts = load_hosts_config()
    try:
        d = hosts[hostname]
    except KeyError:
        raise ConfigException("Host {} not configured.".format(hostname))

    # add global information, that is necessary for the templates
    d.update(global_config())
    return d

def find_hostname_by_mac(mac, hosts=None):
    if hosts is None:
        hosts = load_hosts_config()
    for name,config in hosts.items():
        try:
            if config['mac'].lower() == mac.lower():
                return name
        except KeyError:
            pass
    return None

def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:  # Python >2.5
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise

def template_pyfounder_update_status(cfg, status="unknown"):
    tpl = """# pyfounder_update_status("{status}")
if [ -x /bin/curl ]; then
    /bin/curl -o /dev/null --silent {url}/report/state/{mac}/{status}
elif [ -x /bin/wget ]; then
    /bin/wget -q -O /dev/null {url}/report/state/{mac}/{status}
elif [ -x /usr/bin/wget ]; then
    /usr/bin/wget -q -O /dev/null {url}/report/state/{mac}/{status}
else
    wget -q -O /dev/null {url}/report/state/{mac}/{status}
fi
    """

    try:
        snippet = tpl.format(
            url = cfg['pyfounder_url'],
            mac = cfg['mac'],
            status = status
            )
    except Exception as e:
        estr = '{}: {}'.format(type(e).__name__, e)
        return "# Error in {{ pyfounder_update_status("+status+") }}: " + estr
    return snippet

def configured_template(template_file, cfg={}):
    # load the jinja stuff
    from jinja2 import FileSystemLoader, Environment
    from jinja2.exceptions import TemplateNotFound
    # create context
    context = cfg
    for key, value in cfg['variables'].items():
        context[key] = value
    # FIXME: should env be global?
    env = Environment(
            loader=FileSystemLoader(get_template_directory()))
    try:
        # load template
        template = env.get_template(template_file)
    except jinja2.exceptions.TemplateNotFound as e:
        raise ConfigException("Template {} not found.".format(template_file))
    # add custom functions
    template.globals['pyfounder_update_status'] = \
            lambda x: template_pyfounder_update_status(cfg, x)

    # render
    rendered_content = template.render(**context)
    return rendered_content

def row2dict(row):
    d = {}
    for column in row.__table__.columns:
        d[column.name] = getattr(row, column.name)
    return d


def empty_or_None(s):
    if s is None:
        return True
    if len(s.strip())<1:
        return True
    return False


def fetch_template(template_name, hostname):
    cfg = host_config(hostname)
    from pprint import pprint
    # find template filename
    try:
        template_file = cfg['templates'][template_name]
    except KeyError as e:
        raise ConfigException("Template {} not configured for host {}\n{}".format(
            template_name, hostname, e))
    try:
        rendered_content = configured_template(template_file,cfg)
    except Exception as e:
        raise ConfigException("Error configuring Template {} for host {}\n{}".format(
            template_name, hostname, e))
    return rendered_content


def fetch_template_pxe_discovery():
    s = """default pyfounder-discovery
timeout 0
LABEL pyfounder-discovery
        kernel pyfounder-discovery/vmlinuz
        append initrd=pyfounder-discovery/initrd boot=live nomodeset fetch=tftp://{{pyfounder_ip}}/pyfounder-discovery/filesystem.squashfs PYFOUNDER_SERVER={{pyfounder_url}}
"""
    cfg = global_config()
    from jinja2 import BaseLoader, Environment
    t = Environment(loader=BaseLoader).from_string(s)
    return t.render(**cfg)

#def config_host_data(_hostdata, hosts_config=None):
#    result = []
#    if hosts_config is None:
#       hosts_config = load_hosts_config()
#    for _host in _hostdata:
#        host = dict(_host_default_data)
#        host.update(_host)
#        _hc = None
#        if not empty_or_None(host['mac']):
#            _hn = find_hostname_by_mac(host['mac'],hosts_config)
#            _hc = hosts_config[_hn]
#        if _hc is None and host['name'] in hosts_config:
#            _hc = hosts_config[host['name']]
#        if _hc is not None:
#            host.update(_hc)
#        # restore the state
#        try:
#            host['state'] = _host['state']
#        except KeyError:
#            pass
#        print(host['state'])
#        result.append(host)
#    return result


def fnmatch2sql(pattern):
    return pattern
