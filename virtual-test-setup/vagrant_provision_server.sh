#!/bin/bash

set -e

export DEBIAN_FRONTEND=noninteractive

mkdir -p /var/lib
test -L /var/lib/tftpboot || ln -s /vagrant/tftpboot /var/lib/tftpboot

apt-get update -y
apt-get install -y dnsmasq

IP=10.0.10.10

cat << EOF >/etc/dnsmasq.conf
# dont read /etc/hosts
no-hosts
# read hosts from here
addn-hosts=/etc/dnsmasq.hosts
# listen on this address
listen-address=127.0.0.1,${IP}
# set the dhcp range
dhcp-range=10.0.10.11,10.0.10.20,1h
# set the ntp server
dhcp-option=option:ntp-server,${IP}
# set the gateway
dhcp-option=option:router,${IP}
# pxe boot via
dhcp-boot=/pxelinux.0,${IP}
# tftp
enable-tftp
tftp-root=/var/lib/tftpboot
EOF

cat << EOF >/etc/dnsmasq.hosts
10.0.10.10	server
10.0.10.11	client
EOF

# disabled systemd-resolved
systemctl disable systemd-resolved
systemctl stop systemd-resolved

# update /etc/resolv.conf
cat << EOF >/etc/resolv.conf
nameserver 127.0.0.1
nameserver 8.8.8.8
EOF

systemctl restart dnsmasq.service

# apt-cacher
apt-get install -y apt-cacher-ng

OUTER_IF=enp0s3
INNER_IF=enp0s8

iptables -A FORWARD -o $OUTER_IF -i $INNER_IF -s 10.0.10.0/24 -m conntrack --ctstate NEW -j ACCEPT
iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 
iptables -t nat -A POSTROUTING -o $OUTER_IF -j MASQUERADE
# iptables -A FORWARD -o $OUTER_IF -s 10.0.10.0/16 -m conntrack --ctstate NEW -j ACCEPT 