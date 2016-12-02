#!/usr/bin/env python

'''
This scripts configures a UCSM from blank config.  The fabric setup I was
tasked with creating had two disjoint uplinks.  One uplink connected
to the PXE network (Eth1/32) while the main uplink (Eth2/16) carried all the
remaining VLANs.  Each server was to have 100 vNICs.  One vNIC was for
the PXE network (VLAN4093), one was for the MGMT network (VLAN501), and
the other 98 were for virtual topologies that ran on top of each server.
Each of these virtual topologies required 11 VLANs.  1 VLAN (in the 1000
range) was routable, while the remaining 10 (in the 2000 range) were not.
All the servers had 8 drives which were to be configured in RAID10.  Also,
the server needed to be configured for IPMI.

Some of the vars I pulled out and put at the top of the script b/c
they were used in several places.  But some stuff I hardcoded (like
the uplink ports).

The script is divided into to chunks.  The first chunk is global config.
The second chunk is all the config that is put into an org.  There is a
variable which determines if the global config is to be applied or not.
The idea is it will take you several iterations of this script to get
the config exactly right.  So iterate over the global configs first
and get those how you like them.  This is the harder part as you will
have to manually go back and delete incorrect entries, so wipe your UCSM
config and start from scratch.  Once the globals are correct, flip the
variable and iterate over the org items. This is much quicker b/c when
you get it wrong, you just delete the org, and run the script again.
'''

from os import urandom
from binascii import b2a_hex
from netaddr import IPNetwork, IPAddress
# Import Ucs library
from ucsmsdk.ucshandle import UcsHandle
# Import time functions from samples repo
from ucsmsdk_samples.admin.timezone import time_zone_set, ntp_server_create
# Import the org functions from samples
from ucsmsdk_samples.server.org import org_create
# Import the uplink port-type object
from ucsmsdk.mometa.fabric.FabricEthLanEp import FabricEthLanEp
# Import the function to create server ports from samples library
from ucsmsdk_samples.network.server_port import server_port_create
# import the function from samples to create VLANs
from ucsmsdk_samples.network.vlan import vlan_create
# import the function from samples to create MAC pools
from ucsmsdk_samples.network.mac_pools import mac_pool_create
# import the function from samples to create vNIC templates
from ucsmsdk_samples.network.vnic import vnic_template_create
# import the function from samples to create and modify LAN connection policies
from ucsmsdk_samples.network.lan_conn_policy import lan_conn_policy_create, \
                                                    add_vnic
# import the function from samples to create IP pools and IP blocks
from ucsmsdk_samples.network.ip_pools import ip_pool_create, add_ip_block
# import the function from samples to boot policy
from ucsmsdk_samples.server.boot_policy import boot_policy_create
# import the function from samples to create local disk policy
from ucsmsdk_samples.server.local_disk_policy import local_disk_policy_create
# import the function from samples to create service profile template
from ucsmsdk_samples.server.service_profile import sp_template_create, \
                                                   sp_create_from_template
# import the functions to create server pools
from ucsmsdk.mometa.compute.ComputePool import ComputePool
from ucsmsdk.mometa.compute.ComputePooledRackUnit import ComputePooledRackUnit
from ucsmsdk.mometa.ls.LsRequirement import LsRequirement
# import the functions to add PXE to boot policy
from ucsmsdk.mometa.lsboot.LsbootLan import LsbootLan
from ucsmsdk.mometa.lsboot.LsbootLanImagePath import LsbootLanImagePath
# import functions to configure disjoint VLANs
from ucsmsdk.mometa.fabric.FabricEthVlanPortEp import FabricEthVlanPortEp
# import functions to set drive mode
from ucsmsdk.mometa.storage.StorageLocalDisk import StorageLocalDisk
from ucsmsdk.ucsexception import UcsException
# import functions to set create ipmi policy
from ucsmsdk.mometa.aaa.AaaEpAuthProfile import AaaEpAuthProfile
from ucsmsdk.mometa.aaa.AaaEpUser import AaaEpUser


# Vars to use throughout Config
perform_non_org_config = True
topo_slots = range(98)  # breaks at 100
vlan_per_slot = 10
rack_servers = range(1, 21)
server_ports = range(1, 12)
server_ports.extend(range(17, 26))
KVM_IP_gateway = IPNetwork("169.254.10.1/24")
KVM_IP_start = IPAddress('169.254.10.5')


# login to UCSM
handle = UcsHandle('10.18.183.2', 'admin', 'password')
if not handle.login():
    raise "Error during login"


#######################
# Fabric-wide configs #
#######################
if perform_non_org_config:
    print "Setting timezone and NTP"
    # UCS is in SJC so set to Pacific time
    time_zone_set(handle, 'America/Los_Angeles')
    # Configure two of the  NTP servers
    ntp_server_create(handle, "1.pool.ntp.org", "NTP1")
    ntp_server_create(handle, "2.pool.ntp.org", "NTP2")

    print "Setting server ports"
    # Configure the same ports on both fabric A and B
    for dn in ('fabric/server/sw-A', 'fabric/server/sw-B'):
        # Port 1/1-11,17-26 are connected to servers
        for port_id in server_ports:
            # Set port on fabric to server type.
            server_port_create(handle, dn=dn,
                               port_id=str(port_id), slot_id=str(1))

    print "Setting uplink ports to ToR"
    # Configure the same ports on both fabric A and B
    for dn in ('fabric/lan/A', 'fabric/lan/B'):
        # Create uplink port-type object for port 2/16
        # Fabric is specified using the parent_mo_or_dn
        mo = FabricEthLanEp(parent_mo_or_dn=dn,
                            slot_id=str(2), port_id=str(16))
        # Add the uplink port-type object to the UCSM
        handle.add_mo(mo, modify_present=False)
        # Apply the changes
        handle.commit()

    print "Setting uplink ports to PXE network"
    # Configure the same ports on both fabric A and B
    for dn in ('fabric/lan/A', 'fabric/lan/B'):
        # Create uplink port-type object for port 1/32
        # Fabric is specified using the parent_mo_or_dn
        mo = FabricEthLanEp(parent_mo_or_dn=dn,
                            slot_id=str(1), port_id=str(32))
        # Set the speed to 1Gbps since GLC-T SFP is used to connect to PXE
        mo.admin_speed = '1gbps'
        # Add the uplink port-type object to the UCSM
        handle.add_mo(mo, modify_present=False)
        # Apply the changes
        handle.commit()

    print "Creating VLANs"
    # We are creating max_slot slots.  Each slot is a set of 11 VLANs
    # The first vlan comes from the lab-routable 1k range.
    # The remaining VLANs are contiguous and come from the topo-local 2k+ range
    vlan_list = list()
    for slot in topo_slots:
        # VLAN_id is based on slot number
        vlan_id = 1000 + slot
        # Specify the slot, id and function in the VLAN name
        name = 'Slot{0:03d}-{1}-routable'.format(slot, vlan_id)
        print "Creating Vlan {0}".format(name)
        # Create the first vlan in the set
        vlan_list.append(vlan_create(handle, name, str(vlan_id)))
        # create the remaining vlan_per_slot vlans
        for vlan in range(vlan_per_slot):
            # vlan_id is based on slot
            vlan_id = 2000 + vlan + slot * vlan_per_slot
            # Specify the slot, and vlan_id in the VLAN name
            name = 'Slot{0:03d}-{1}'.format(slot, vlan_id)
            print "Creating Vlan {0}".format(name)
            # Create the vlan
            vlan_list.append(vlan_create(handle, name, str(vlan_id)))
    # Create VLAN501 on UCSM matching upstream VLAN501
    vlan_list.append(vlan_create(handle, 'MGMT-501', str(501)))
    # Assign the all the VLANs to only the 2/16 uplink on both fabrics
    print "Assiging vlans to port 2/16"
    for vlan_mo in vlan_list:
        for fabric in ("A", "B"):
            FabricEthVlanPortEp(parent_mo_or_dn=vlan_mo, switch_id=fabric,
                                slot_id="2", port_id="16")
        handle.add_mo(vlan_mo, True)
    handle.commit()
    # Use the highest VLAN id available for PXE network
    vlan_mo = vlan_create(handle, 'PXE-4093', str(4093))
    # Assign the VLAN to only the 1/32 uplink on both fabrics
    print "Assiging vlans to port 1/32"
    for fabric in ("A", "B"):
        FabricEthVlanPortEp(parent_mo_or_dn=vlan_mo, switch_id=fabric,
                            is_native="yes", slot_id="1", port_id="32")
    handle.add_mo(vlan_mo, True)
    handle.commit()

    # Set disks on all nodes to Unconfigured Good
    print "Setting disks to Unconfigured state"
    for rack_unit in rack_servers:
        dn = "sys/rack-unit-{0}/board/storage-SAS-1".format(rack_unit)
        for disk in range(1, 9):
            mo = StorageLocalDisk(parent_mo_or_dn=dn, id=str(disk),
                                  admin_action="unconfigured-good",
                                  admin_action_trigger="triggered")
            handle.add_mo(mo, True)
            try:
                handle.commit()
            except UcsException:
                print "server-{0} drive {1} already in \
                       unconfigured-good".format(rack_unit, disk)

###############################
# Configs within the topo org #
###############################
print "Creating topo org"
# Create an org named topo for to house all policies/pools/etc
topo_org = org_create(handle, 'topo')

print "Creating MAC address pools"
random_hex = b2a_hex(urandom(1))
# Create a different pool for each slot
for slot in topo_slots:
    # Name the pool based on the slot
    name = "Slot{0:03d}-MAC".format(slot)
    # Convert slot number to hex and use that as an identifier in the pool
    r_from = "00:25:B5:{1}:{0:02x}:00".format(slot, random_hex)
    # Assign all MACs (from 00 to FF ) within the identifier to the slot
    to = "00:25:B5:{1}:{0:02x}:FF".format(slot, random_hex)
    # Create the per-slot pool in the topo org
    print "Creating MAC pool {0}".format(name)
    mac_pool_create(handle, name=name, assignment_order="default",
                    r_from=r_from, to=to, parent_dn=topo_org.dn)
# Create a pool for the PXE network
mac_pool_create(handle, name="PXE-MAC", assignment_order="default",
                r_from="00:25:B5:{0}:FF:00".format(random_hex),
                to="00:25:B5:{0}:FF:3F".format(random_hex),
                parent_dn=topo_org.dn)
# Create a pool for the MGMT network
mac_pool_create(handle, name="MGMT-MAC", assignment_order="default",
                r_from="00:25:B5:{0}:FF:40".format(random_hex),
                to="00:25:B5:{0}:FF:7F".format(random_hex),
                parent_dn=topo_org.dn)


print "Creating vNICs"
# Create a vNIC for each slot
for slot in topo_slots:
    # Name the vNIC after the slot
    vnic_name = 'Slot{0:03d}'.format(slot)
    # Odd slots will be primary on fabric A,
    # while even slots will be primary on fabric B
    # switch_id = "A-B" if slot % 2 else "B-A"
    switch_id = "A-B" if slot % 2 else "B-A"
    # Create a list of the vlan names in each slot.
    # The first vlan in the slot is the lab-routable vlan
    vlan_name = 'Slot{0:03d}-{1}-routable'.format(slot, slot + 1000)
    # The "yes" means the VLAN is native (untagged) VLAN on the vnic
    # to allow VM PXE.
    vlan_list = [(vlan_name, "yes")]
    ident_pool_name = "Slot{0:03d}-MAC".format(slot)
    for vlan in range(vlan_per_slot):
        # The rest of the vlans in the slot are the topo-local in the 2k+ range
        vlan_id = 2000 + vlan + slot * vlan_per_slot
        vlan_name = 'Slot{0:03d}-{1}'.format(slot, vlan_id)
        # "no" means the remaining vlans in the slot will be tagged.
        vlan_list.append((vlan_name, "no"))
    # Create an updating vNIC template in topo org
    # with all the vlans in the slot
    # Setting the MTU is just a workaround for
    # https://github.com/CiscoUcs/ucsmsdk_samples/issues/25
    print "Creating vNIC for slot Slot{0:03d}".format(slot)
    vnic_template_create(handle, name=vnic_name, vlans=vlan_list,
                         ident_pool_name=ident_pool_name, switch_id=switch_id,
                         templ_type="updating-template",
                         parent_dn=topo_org.dn, mtu="1500")
# Create an updating vNIC template for PXE network, which is primary on fab A
# "yes" means this will be the native (untagged) for the vNIC
vnic_template_create(handle, name="PXE", vlans=[("PXE-4093", "yes")],
                     ident_pool_name="PXE-MAC", switch_id="A-B",
                     templ_type="updating-template",
                     parent_dn=topo_org.dn, mtu="1500")
# Create an updating vNIC tempalte for MGMT network, which is primary on fab B
# "yes" means this will be the native (untagged) for the vNIC
vnic_template_create(handle, name="MGMT", vlans=[("MGMT-501", "yes")],
                     ident_pool_name="MGMT-MAC", switch_id="B-A",
                     templ_type="updating-template",
                     parent_dn=topo_org.dn, mtu="1500")


print "Creating LAN connection policy"
# Create a new LAN connection policy for hypvsr servers in the topo org,
# saving the return val
hypvsr_lan_policy = lan_conn_policy_create(handle, name="hypvsr-lan",
                                           parent_dn=topo_org.dn)
# Add a vNIC to the lan connection policy (as specified by its DN) for the PXE
# network using the PXE vNIC template
add_vnic(handle, hypvsr_lan_policy.dn, "PXE", nw_templ_name="PXE")
# Add a vNIC to the lan connection policy (as specified by its DN) for the MGMT
# network using the MGMT vNIC template
add_vnic(handle, hypvsr_lan_policy.dn, "MGMT", nw_templ_name="MGMT")
# Loop over all the slots
for slot in topo_slots:
    # Re-derive the name of the previously created vNIC template based on slot
    vnic_name = 'Slot{0:03d}'.format(slot)
    # Add a vNIC to the lan connection policy (as specified by its DN) for each
    # slot using the slot vNIC template
    print "Adding {0} to LAN Connection Policy".format(vnic_name)
    add_vnic(handle, hypvsr_lan_policy.dn, vnic_name, nw_templ_name=vnic_name)


print "Creating KVM ip pool"
# Create a pool in the topo org from which to assign the KVM IP of each server
ip_pool = ip_pool_create(handle, "kvm", "default",
                         parent_dn=topo_org.dn)
# Calculate the end address based on start and number of servers
for i, j in enumerate(KVM_IP_gateway):
    if j == KVM_IP_start:
        KVM_IP_end = KVM_IP_gateway[i+len(rack_servers)-1]
        break
# Create an address block within the pool.
# Specify start, end, netmask, gateway, and DNS servers.
add_ip_block(handle, str(KVM_IP_start), str(KVM_IP_end),
             str(KVM_IP_gateway.netmask), str(KVM_IP_gateway.ip),
             "208.67.222.222", "208.67.220.220", ip_pool.dn)


print "Creating IPMI Access policy"
# Create a pool in the topo org from which to assign the KVM IP of each server
ipmi_policy = AaaEpAuthProfile(parent_mo_or_dn=topo_org, policy_owner="local",
                               ipmi_over_lan="enable", name="topo_ipmi_policy")
AaaEpUser(parent_mo_or_dn=ipmi_policy, pwd="password",
          name="admin", priv="admin")
handle.add_mo(ipmi_policy)
handle.commit()


print "Creating boot policy"
# Boot order is local-disk for now.  Later we can add pxe, when code is written
boot_order = {"2": "local-disk"}
# Create the boot policy in the topo org,
# that doesn't reboot the host if the order changes.
boot_policy = boot_policy_create(handle, name="hypvsr-boot",
                                 reboot_on_update="no",
                                 parent_dn=topo_org.dn,
                                 boot_device=boot_order)
# Add PXE to boot policy and re-apply
lan_boot = LsbootLan(parent_mo_or_dn=boot_policy, prot="pxe", order="1")
LsbootLanImagePath(parent_mo_or_dn=lan_boot, vnic_name="PXE", type="primary")
handle.add_mo(lan_boot, True)
handle.commit()


print "Creating local disk policy"
# Create a RAID10 (raid-mirrored-striped) policy with no flexflesh in topo org.
disk_policy = local_disk_policy_create(
    handle, name="RAID10", mode="raid-mirrored-striped",
    flex_flash_state="disable", flex_flash_raid_reporting_state="disable",
    parent_dn=topo_org.dn
)

print 'Creating server pool'
# Create server pool in topo org
server_pool = ComputePool(parent_mo_or_dn=topo_org, name="hypvsr")
# Add rack servers to pool
for server_id in rack_servers:
    ComputePooledRackUnit(parent_mo_or_dn=server_pool, id=str(server_id))
handle.add_mo(server_pool)
handle.commit()


print "Creating service profile template"
# Create service profile template in the topo org including IP pool,
# boot policy, lan connection policy, and local disk disk policy.
hypvsr_template = sp_template_create(
    handle, name="hypvsr-topo",
    type="updating-template",
    resolve_remote="yes", ext_ip_state="pooled",
    ext_ip_pool_name="kvm", boot_policy_name="hypvsr-boot",
    mgmt_access_policy_name="topo_ipmi_policy",
    lan_conn_policy_name="hypvsr-lan",
    local_disk_policy_name="RAID10",
    parent_dn=topo_org.dn
)
# Add server pool to template
LsRequirement(parent_mo_or_dn=hypvsr_template,
              restrict_migration="no", name="hypvsr", qualifier="")
handle.add_mo(hypvsr_template, True)
handle.commit()

# Create service profiles for each server from template
sp_create_from_template(handle, naming_prefix="hypvsr-",
                        name_suffix_starting_number="1",
                        number_of_instance=str(len(rack_servers)),
                        sp_template_name="hypvsr-topo",
                        parent_dn=topo_org.dn)
