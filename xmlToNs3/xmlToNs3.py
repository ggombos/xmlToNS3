# /*
#  * This program is free software; you can redistribute it and/or modify
#  * it under the terms of the GNU General Public License version 2 as
#  * published by the Free Software Foundation;
#  *
#  * This program is distributed in the hope that it will be useful,
#  * but WITHOUT ANY WARRANTY; without even the implied warranty of
#  * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  * GNU General Public License for more details.
#  *
#  * You should have received a copy of the GNU General Public License
#  * along with this program; if not, write to the Free Software
#  * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#  */

# cd contrib
# git clone https://gitlab.com/cttc-lena/nr.git
# cd nr/
# git checkout -b 5g-lena-v4.1.y origin/5g-lena-v4.1.y

# ./ns3 configure --enable-examples --enable-tests --enable-python-bindings --disable-module=netsimulyzer --enable-module=netanim,nr,point-to-point-layout


import configparser
import cppyy
cppyy.add_include_path("include")
cppyy._cppyy_enable_fast_cache = True

import sys 
sys.path.append("./ns-3-dev/build/bindings/python")
sys.path.append("./ns-3-dev/build/lib")

from ns import ns

import os
import glob
# import random
from collections import defaultdict, deque
import heapq
import math


collectedDevices = {}
collectedCameraApps = {}
collectedSensorApps = {}
devices = []
ownNodes = {}
servers = []
nodes = None

ns.Packet.EnablePrinting()

ns.LogComponentEnable("UdpClient", ns.LOG_LEVEL_INFO)
ns.LogComponentEnable("UdpServer", ns.LOG_LEVEL_INFO)
ns.LogComponentEnable("Ipv4L3Protocol", ns.LOG_LEVEL_INFO)
#ns.LogComponentEnable("TrafficGenerator", ns.LOG_LEVEL_INFO)
# ns.LogComponentEnable("WifiMac", ns.LOG_LEVEL_INFO)
# ns.LogComponentEnable("WifiPhy", ns.LOG_LEVEL_INFO)

ns.cppyy.cppdef("""
			using namespace ns3;

			Callback<void,Ptr<const Packet>,const Address&,const Address&>
			make_sinktrace_callback(void(*func)(Ptr<const Packet>, const Address&,const Address&))
			{
				return MakeCallback(func);
			}
		""")


def SinkTracer(packet: ns.Packet, src_address: ns.Address, dst_address: ns.Address) -> None:
	print(f"At {ns.Simulator.Now().GetSeconds():.0f}s, '{dst_address}' received packet"
		  f" with {packet.__deref__().GetSerializedSize()} bytes from '{src_address}'")

sinkTraceCallback = ns.cppyy.gbl.make_sinktrace_callback(SinkTracer)


def storeOwnNodeId(n1, n2):
	ownNodes[n1] = 1
	ownNodes[n2] = 1


def change_bw (dev, new_kbps):	
	dev.SetDataRate(ns.DataRate(str(new_kbps)+"Kbps"))

def change_app_rate(app,interval):
    app.SetAttribute("Interval", ns.TimeValue(ns.MilliSeconds(interval)))  # 0.05 s csomagköz
    print("UDP rátaváltás, új interval:", interval, "ms @", ns.Simulator.Now().GetSeconds(), "s")

def ConfigureXrApp(ueContainer,i,ueIpIface,config,appDataRate,appFps,port,transportProtocol,remoteHostContainer,ueNetDev,nrHelper,bearer,tft,isMx1,tfts,serverApps,clientApps,pingApps,needBearer=True):
	trafficMixerHelper = ns.XrTrafficMixerHelper();
	ipAddress = ueIpIface.GetAddress(i, 0)
	trafficMixerHelper.ConfigureXr(config)
	it = ns.XrPreconfig.find(config)

	addresses = cppyy.gbl.std.vector(ns.Address)()
	localAddresses = cppyy.gbl.std.vector(ns.InetSocketAddress)()
	for j in range(it.second.size()):
		addresses.emplace_back(ns.InetSocketAddress(ipAddress, port + j).ConvertTo())
		# The sink will always listen to the specified ports
		localAddresses.emplace_back(ns.InetSocketAddress (ns.Ipv4Address.GetAny(), port + j))

	currentUeClientApps = ns.ApplicationContainer()
	currentUeClientApps.Add(
		trafficMixerHelper.Install(transportProtocol, addresses, remoteHostContainer.Get(0)))

	# Seed the ARP cache by pinging early in the simulation
	# This is a workaround until a static ARP capability is provided
	ping = ns.PingHelper(ns.Ipv4Address(ipAddress).ConvertTo())
	pingApps.Add(ping.Install(remoteHostContainer))

	if needBearer:
		ueDevice = ueNetDev.Get(i)
		# Activate a dedicated bearer for the traffic type per node
		# nrHelper.ActivateDedicatedEpsBearer(ueDevice, bearer, tft)
		# Activate a dedicated bearer for the traffic type per node
		if isMx1:
			nrHelper.ActivateDedicatedEpsBearer(ueDevice, bearer, tft)
		else:
			for j in range(currentUeClientApps.GetN()):
				nrHelper.ActivateDedicatedEpsBearer(ueDevice, bearer, tfts[j])

	for j in range(currentUeClientApps.GetN()):
		dlPacketSinkHelper = ns.PacketSinkHelper (transportProtocol, localAddresses[j].ConvertTo())
		packetSink = dlPacketSinkHelper.Install(ueContainer.Get(i)).Get(0)
		serverApps.Add(packetSink)
		# app = DynamicCast<TrafficGenerator3gppGenericVideo>(currentUeClientApps.Get(j))
		# app = currentUeClientApps.Get(j)
		app = ns.cppyy.gbl.ns3.DynamicCast[
				ns.TrafficGenerator3gppGenericVideo,
				ns.Application
			](currentUeClientApps.Get(j))
		if app:
			app.SetAttribute("DataRate", ns.DoubleValue(appDataRate));
			app.SetAttribute("Fps", ns.UintegerValue(appFps));
	clientApps.Add(currentUeClientApps)


def CollectLinkInterfaces():
	"""
	Kiolvassa a szimulációban már létező kapcsolatokat:
	megmondja, melyik két node melyik interface-en keresztül van összekötve.
	Működik PointToPoint, Csma/Ethernet, Wifi, LTE/NR típusú kapcsolatokra.
	"""
	n_nodes = ns.NodeList.GetNNodes()
	link_map = {}

	print(f"[Topology] {n_nodes} node feldolgozása...")

	# Végigmegyünk minden node-on és device-on
	for i in range(n_nodes):
		node = ns.NodeList.GetNode(i)
		node_name = i

		print("Node:",i,node.GetNDevices())
		for dev_idx in range(node.GetNDevices()):
			dev = node.GetDevice(dev_idx)
			if dev is None:
				print("Device None",dev_idx)
				continue

			ch = dev.GetChannel()
			if not ch:
				print("Channel None",dev_idx)
				continue  # nincs channel, pl. loopback vagy LTE
			if not hasattr(ch, "GetNDevices"):
				print("Not real channel",dev_idx)
				continue  # nem valós Channel objektum (pl. LTE)
			try:
				n_devices = ch.GetNDevices()
			except Exception as e:
				print(e)
				continue  # biztonsági fallback

			if n_devices < 2:
				continue
			# Az aktuális device a csatornán
			other_dev = None
			for j in range(n_devices):
				ch_dev = ch.GetDevice(j)
				if ch_dev != dev:
					other_dev = ch_dev
					break
			if other_dev is None:
				continue

			# Másik node és interfész adatai
			other_node = other_dev.GetNode()
			other_node_idx = None
			for k in range(n_nodes):
				if ns.NodeList.GetNode(k) == other_node:
					other_node_idx = k
					break



			other_dev_idx = -1
			for k in range(other_node.GetNDevices()):
				if other_node.GetDevice(k) == other_dev:
					other_dev_idx = k
					break

			# Interface típus felismerése
			def get_ifname(dev, idx):
				dtype = str(dev.GetInstanceTypeId().GetName())
				if "PointToPoint" in dtype:
					return f"{idx}"
				elif "Csma" in dtype or "Ethernet" in dtype:
					return f"{idx}"
				elif "Wifi" in dtype:
					# return f"{idx+1}" if idx == 0 else f"{idx}"
					return f"{idx}"
				elif "Lte" in dtype or "Nr" in dtype:
					print("nr")
					return f"{idx}"
				else:
					return f"{idx}"

			iface1 = get_ifname(dev, dev_idx)
			iface2 = get_ifname(other_dev, other_dev_idx)

			# Elkerüljük a duplikált bejegyzéseket (A-B és B-A ugyanaz)
			key = f"{node_name}-{other_node_idx}"
			val = f"{iface1}-{iface2}"

			if key not in link_map:
				link_map[key] = val
				print(f"  {node_name}({iface1}) ↔ {other_node_idx}({iface2})")
	print("============")
	return link_map


def BuildRouting(link_data = {}):
	# 2 Gráf felépítése
	graph = defaultdict(list)
	interface_map = {}	# (node1, node2) -> (intf1, intf2)

	for key, val in link_data.items():
		n1, n2 = key.split("-")
		i1, i2 = val.split("-")
		n1, n2 = int(n1), int(n2)
		i1, i2 = int(i1), int(i2)
		graph[n1].append(n2)
		graph[n2].append(n1)
		interface_map[(n1, n2)] = i1
		interface_map[(n2, n1)] = i2

	print(f"[Routing] Gráf felépítve {len(graph)} node-dal és {len(link_data)} linkkel.")

	# 3 Routing táblák létrehozása
	ipv4RoutingHelper = ns.Ipv4StaticRoutingHelper()

	# for src_name, src_node in node_map.items():
	for i in range(ns.NodeList.GetNNodes()):
		src_name, src_node = i, ns.NodeList.GetNode(i)

		if not i in ownNodes:
			print(f"  Node {src_name}: kihagyva")
			continue
		src_ipv4 = src_node.GetObject[ns.Ipv4]()
		src_ipv4.SetAttribute("IpForward", ns.BooleanValue(True))
		if src_ipv4 is None:
			continue

		src_routing = ipv4RoutingHelper.GetStaticRouting(src_ipv4)
		print(f"  Node {src_name}: routing építése...")

		# BFS keresés a legrövidebb utakhoz
		prev = {}
		visited = {src_name}
		q = deque([src_name])

		# print(graph)
		while q:
			cur = q.popleft()
			# print(f"cur {cur}")
			for nxt in graph[cur]:
				# print(f"nxt {nxt}")
				if nxt not in visited:
					visited.add(nxt)
					prev[nxt] = cur
					q.append(nxt)

		# Minden másik node-hoz útvonal hozzáadása
		for j in range(ns.NodeList.GetNNodes()):
			# print(f"{i}-->{j}")
			dst_name, dst_node = j, ns.NodeList.GetNode(j)
			if dst_name == src_name:
				continue
			if dst_name not in prev:
				continue  # nincs kapcsolat
			# print(f"{i}-->{j}")

			# Útvonal visszafejtése: src → ... → dst
			path = [dst_name]
			while path[-1] in prev:
				path.append(prev[path[-1]])
			path = list(reversed(path))

			# print(path)

			if len(path) < 2:
				continue

			# Következő hop az első szomszéd
			next_hop = path[1]
			print(f"nexthop {next_hop}")
			# A kimeneti interfész a src -> next_hop linkhez tartozik
			intf_name = interface_map.get((src_name, next_hop), "?")
			
			next_hop_ipv4 = ns.NodeList.GetNode(next_hop).GetObject[ns.Ipv4]()
			if next_hop_ipv4 is None or next_hop_ipv4.GetNInterfaces() == 0:
				continue

			# next_hop_addr = next_hop_ipv4.GetAddress(intf_name, 0).GetLocal()
			nh_intf_name = interface_map.get((next_hop, src_name), "?")
			next_hop_addr = next_hop_ipv4.GetAddress(nh_intf_name, 0).GetLocal()
			
			# Célnode IP címének lekérése
			dst_ipv4 = dst_node.GetObject[ns.Ipv4]()
			if dst_ipv4 is None or dst_ipv4.GetNInterfaces() == 0:
				continue
				
			for intfN in range(1,dst_ipv4.GetNInterfaces()):
				# Routing hozzáadása
				try:
					dst_addr = dst_ipv4.GetAddress(intfN, 0).GetLocal()	 # első nem-loopback cím

					# src_routing.AddHostRouteTo(
					src_routing.AddNetworkRouteTo(
						dst_addr,
						ns.Ipv4Mask("255.255.255.255"),
						next_hop_addr,
						intf_name
					)
					src_routing.AddNetworkRouteTo(
						dst_addr,
						ns.Ipv4Mask("255.255.255.0"),
						intf_name
					)
					print(f"	{src_name} → {dst_name} útvonal felvéve {dst_addr} via {next_hop} ({intf_name})")
				except Exception as e:
					print(f"	{src_name}->{dst_name} route kihagyva: {e}")

	print("[Routing] Statikus routing generálás kész.")

def createPointToPointLink(link,datarate="100Mbps", delay="40ms", ):
	global collectedDevices
	srcId, dstId = map(int,link.split("-"))

	pointToPoint = ns.PointToPointHelper()
	pointToPoint.SetDeviceAttribute("DataRate", ns.StringValue(datarate))
	#default DropTailQueue
	# pointToPoint.SetQueue ("ns3::DropTailQueue", "MaxSize", ns.StringValue ("1000p"));
	pointToPoint.SetChannelAttribute("Delay", ns.StringValue(delay))


	nc = ns.NodeContainer()
	nc.Add(nodes.Get(srcId))
	nc.Add(nodes.Get(dstId))
	dev = pointToPoint.Install(nc)
	devices.append(dev)
	
	collectedDevices[link] = dev

	storeOwnNodeId(srcId, dstId)
	
	# forward
	schedQueueDisc = ns.TrafficControlHelper()

	# schedQueueDisc.SetRootQueueDisc("ns3::DropTailQueue", "MaxSize",ns.StringValue ("1000p"))
	qdiscCont = schedQueueDisc.Install(dev.Get(0))

	# backward
	schedQueueDisc = ns.TrafficControlHelper()
	# schedQueueDisc.SetRootQueueDisc("ns3::DropTailQueue", "MaxSize",ns.StringValue ("1000p"))
	qdiscCont = schedQueueDisc.Install(dev.Get(1))

	
# -------- Main --------------


cppyy.cppdef("""
#include "ns3/config.h"
#include "ns3/nr-gnb-rrc.h"
#include "ns3/core-module.h"

void SetEpsBearerToRlcMapping(bool useUdp) {
	ns3::Config::SetDefault("ns3::NrGnbRrc::EpsBearerToRlcMapping",
		ns3::EnumValue(useUdp ? ns3::NrGnbRrc::RLC_UM_ALWAYS : ns3::NrGnbRrc::RLC_AM_ALWAYS));
}
""")

ns.cppyy.cppdef("""
			EventImpl* pythonMakeEventBW(void (*f)(ns3::Ptr<ns3::NetDevice>, int), ns3::Ptr<ns3::NetDevice> dev, int kbps)
			{
				return MakeEvent(f, dev, kbps);
			}
		""")

ns.cppyy.cppdef("""
			EventImpl* pythonMakeEventApp(void (*f)(ns3::Ptr<ns3::Object>, int), ns3::Ptr<ns3::Object> app, float interval)
			{
				return MakeEvent(f, app, interval);
			}
		""")

def reset():
	global nodes, devices, collectedDevices, collectedCameraApps, collectedSensorApps, ownNodes, servers
	collectedDevices = {}
	collectedCameraApps = {}
	collectedSensorApps = {}
	devices = []
	ownNodes = {}
	servers = []
	nodes = None

def blockPrint():
	sys.stdout = open(os.devnull, 'w')

# Restore
def enablePrint():
	sys.stdout = sys.__stdout__


def runSim(withPrint=False, configFile="xmlToNs3/config.conf"):
	global nodes, devices, collectedDevices, collectedCameraApps, collectedSensorApps, ownNodes, servers
	reset()
	blockPrint()
	if withPrint:
		enablePrint()
	
	conf = configparser.ConfigParser()
	conf.read(configFile)
	
	ns.RngSeedManager.SetSeed(int(conf['DEFAULT']['rndSeed']))

	# random.seed(4682)
	tcpBufferMulti = 3

	ns.Config.SetDefault("ns3::TcpSocket::SegmentSize", ns.UintegerValue (800))
	ns.Config.SetDefault("ns3::TcpSocket::SndBufSize", ns.UintegerValue (131072*tcpBufferMulti))
	ns.Config.SetDefault("ns3::TcpSocket::RcvBufSize", ns.UintegerValue (131072*tcpBufferMulti))
	ns.Config.SetDefault ("ns3::TcpSocket::DelAckCount", ns.UintegerValue (1));
	ns.GlobalValue.Bind("ChecksumEnabled", ns.BooleanValue(False))
	print("TCP: NewReno")
	ns.Config.SetDefault ("ns3::TcpL4Protocol::SocketType", ns.TypeIdValue (ns.TcpNewReno.GetTypeId ()))
	# socketFactory = "ns3::TcpSocketFactory"
	socketFactory = "ns3::UdpSocketFactory"
	ns.Config.SetDefault ("ns3::TcpSocketBase::UseEcn", ns.StringValue ("Off"))


	try:
		os.mkdir('log')
	except:
		pass

	files = glob.glob('log/*')
	for f in files:
		os.remove(f)

	nodes = ns.NodeContainer()
	nodes.Create(int(conf['DEFAULT']['numNodes']))

	mobility = ns.MobilityHelper()
	mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel")
	mobility.Install(nodes)

	stack = ns.InternetStackHelper()
	stack.SetIpv6StackInstall(False);
	stack.Install(nodes)

	# create Ethernet
	if 'Ethernet' in conf:
		for link in conf['Ethernet']['links'].split(","):
			if not link:
				continue
			srcId, dstId = map(int,link.split("-"))
			print(srcId,"--ETH-->",dstId)
			createPointToPointLink(link,"1000Mbps","40ms")

	# create USB2
	if 'USB2' in conf:
		for link in conf['USB2']['links'].split(","):
			if not link:
				continue
			srcId, dstId = map(int,link.split("-"))
			print(srcId,"--USB2-->",dstId)

			createPointToPointLink(link,"480Mbps","1us")

	# create USB3
	if 'USB3' in conf:
		for link in conf['USB3']['links'].split(","):
			if not link:
				continue
			srcId, dstId = map(int,link.split("-"))
			print(srcId,"--USB3-->",dstId)
			createPointToPointLink(link,"5Gbps","1us")

	# internet stackhelper utan kell, de az ip kiosztas elott
	address = ns.Ipv4AddressHelper()

	i = 1
	for d in devices:
		ip1 = str(int(i / 254)+1)
		ip2 = str(int(i % 254)+1)

		address.SetBase(ns.Ipv4Address("200."+ip1+"."+ip2+".0"),
					ns.Ipv4Mask("255.255.255.0"))
		intf = address.Assign(d)
		#interfaces.append(intf)
		i += 1


	#-------------------------------------
	interfaces = {}
	if 'WiFi' in conf:
		apList = conf['WiFi']['AP'].split(";")
		clientsList = conf['WiFi']['clients'].split(";")

		if apList:
			for i in range(len(apList)):
				apNodeId = int(apList[i])
				gateway = nodes.Get(apNodeId)

				wifi = ns.WifiHelper()
				wifi.SetStandard(ns.WIFI_STANDARD_80211n)
				phy = ns.YansWifiPhyHelper()
				channel = ns.YansWifiChannelHelper.Default()
				phy.SetChannel(channel.Create())
				mac = ns.WifiMacHelper()
				ssid = ns.Ssid(f"Wifi-{apNodeId}")

				# Gateway (AP)
				mac.SetType("ns3::ApWifiMac", "Ssid", ns.SsidValue(ssid))
				GWDevice = wifi.Install(phy, mac, gateway)
				
				address.SetBase(ns.Ipv4Address(f"30.{i+1}.1.0"), ns.Ipv4Mask("255.255.255.0"))



				for clientId in map(int,clientsList[i].split(",")):
					print(apNodeId,"<--WiFi-->",clientId)

					client = nodes.Get(clientId)

					# Server (STA)
					mac.SetType("ns3::StaWifiMac", "Ssid", ns.SsidValue(ssid))
					SenDevice = wifi.Install(phy, mac, client )

					# address = ns.Ipv4AddressHelper()
					devic = ns.NetDeviceContainer()
					devic.Add(GWDevice)
					devic.Add(SenDevice)
					_interfaces = address.Assign(devic)
					interfaces[int(apNodeId)] = [_interfaces.GetAddress(0)]
					interfaces[int(clientId)] = [_interfaces.GetAddress(1)]
					
					gwIP = _interfaces.GetAddress(0)
				# dst_ipv4.GetAddress(intfN, 0).GetLocal()
					gw_ipv4 = gateway.GetObject[ns.Ipv4]()
					gw_ipv4.SetAttribute("IpForward", ns.BooleanValue(True))
					cli_ipv4 = client.GetObject[ns.Ipv4]()
					cli_ipv4.SetAttribute("IpForward", ns.BooleanValue(True))

					
					# GW routing
					ipv4RoutingHelper = ns.Ipv4StaticRoutingHelper()
						
					# Sensor Routing
					clientRouting = ipv4RoutingHelper.GetStaticRouting(cli_ipv4)
					clientRouting.AddNetworkRouteTo(
						ns.Ipv4Address(f"30.{i+1}.1.0"), ns.Ipv4Mask("255.255.255.0"), gwIP, 1)
					
					storeOwnNodeId(apNodeId,clientId)
		print("WiFi configured")


	# create Bluetooth
	# http://nsnam.org/doxygen/d0/d69/wifi-trans-example_8cc_source.html

	if 'Bluetooth' in conf:
		for link in conf['Bluetooth']['links'].split(","):
			if not link:
				continue

			gwNodeId, sensorId = map(int,link.split("-"))
			print(gwNodeId,"<--BT-->",sensorId)

			gateway = nodes.Get(gwNodeId)
			sensor = nodes.Get(sensorId)


			# --- "BLE"-ként működő Wi-Fi kapcsolat (kis hatótáv, kis teljesítmény) ---
			wifi = ns.WifiHelper()
			wifi.SetStandard(ns.WIFI_STANDARD_80211b)
			phy = ns.YansWifiPhyHelper()
			channel = ns.YansWifiChannelHelper.Default()
			phy.SetChannel(channel.Create())
			mac = ns.WifiMacHelper()
			ssid = ns.Ssid(f"BLE-{gwNodeId}-{sensorId}")

			# Gateway (AP)
			mac.SetType("ns3::ApWifiMac", "Ssid", ns.SsidValue(ssid))
			GWDevice = wifi.Install(phy, mac, gateway)

			# Server (STA)
			mac.SetType("ns3::StaWifiMac", "Ssid", ns.SsidValue(ssid))
			SenDevice = wifi.Install(phy, mac, sensor )


			# address = ns.Ipv4AddressHelper()
			address.SetBase(ns.Ipv4Address(f"31.1.1.0"), ns.Ipv4Mask("255.255.255.0"))
			devic = ns.NetDeviceContainer()
			devic.Add(GWDevice)
			devic.Add(SenDevice)
			_interfaces = address.Assign(devic)
			interfaces[int(gwNodeId)] = [_interfaces.GetAddress(0)]
			interfaces[int(sensorId)] = [_interfaces.GetAddress(1)]
			
			gwIP = _interfaces.GetAddress(0)
		# dst_ipv4.GetAddress(intfN, 0).GetLocal()
			gw_ipv4 = gateway.GetObject[ns.Ipv4]()
			gw_ipv4.SetAttribute("IpForward", ns.BooleanValue(True))
			sen_ipv4 = sensor.GetObject[ns.Ipv4]()
			sen_ipv4.SetAttribute("IpForward", ns.BooleanValue(True))

			
			# GW routing
			ipv4RoutingHelper = ns.Ipv4StaticRoutingHelper()
			# gwRouting = ipv4RoutingHelper.GetStaticRouting(gw_ipv4)

			# Route sensor subnetre
			# gwRouting.AddNetworkRouteTo(
				# ns.Ipv4Address("30.1.1.0"), ns.Ipv4Mask("255.255.255.0"), gw_ipv4.GetNInterfaces())
				
			# Sensor Routing
			sensorRouting = ipv4RoutingHelper.GetStaticRouting(sen_ipv4)
			sensorRouting.AddNetworkRouteTo(
				ns.Ipv4Address("30.1.1.0"), ns.Ipv4Mask("255.255.255.0"), gwIP, 1)
			
			storeOwnNodeId(gwNodeId,sensorId)


	# ns.Ipv4GlobalRoutingHelper.PopulateRoutingTables()
	# ------------------------------------------

	# -------------- LTE -------------------
	if 'LTE' in conf:

		serverNodes = conf['LTE']['serverNodes'].split(";")
		ueNodes_config = conf['LTE']['UEs'].split(";")

		for config_i in range(len(serverNodes)):
			if not serverNodes[config_i]:
				continue
			serverNode = int(serverNodes[config_i])
			lteHelper = ns.CreateObject[ns.LteHelper]()
			epcHelper = ns.CreateObject[ns.PointToPointEpcHelper]()
			lteHelper.SetEpcHelper(epcHelper)

			pgw = epcHelper.GetPgwNode()
			remoteHost = nodes.Get(serverNode)

			# PGW <-> szerver node: point-to-point
			p2p = ns.PointToPointHelper()
			p2p.SetDeviceAttribute("DataRate", ns.StringValue("100Gb/s"))
			p2p.SetChannelAttribute("Delay", ns.StringValue("2ms"))
			p2pDevices = p2p.Install(pgw, remoteHost)
			
			storeOwnNodeId(pgw.GetId(), serverNode)


			# ipv4h = ns.Ipv4AddressHelper()
			address.SetBase(ns.Ipv4Address("20.0.0.0"), ns.Ipv4Mask("255.255.255.0"))
			internetIpIfaces = address.Assign(p2pDevices)
			# interface 0 is localhost, 1 is the p2p device
			# remoteHostAddr = internetIpIfaces.GetAddress(1)
				
			'''
				Az EPC (PointToPointEpcHelper) belsőleg létrehoz több “láthatatlan” node-ot:
				SGW,
				MME,
				PGW,
				és az S1-U kapcsolatokhoz virtuális “TUN” eszközöket
			  // since we use point-to-point links for all S1-U links, 
			   56	// we use a /30 subnet which can hold exactly two addresses 
			   57	// (remember that net broadcast and null address are not valid)
			   58	m_s1uIpv4AddressHelper.SetBase ("10.0.0.0", "255.255.255.252");
			   59 
			   60	m_x2Ipv4AddressHelper.SetBase ("12.0.0.0", "255.255.255.252");
			   61 
			   62	// we use a /8 net for all UEs
			   63	m_ueAddressHelper.SetBase ("7.0.0.0", "255.0.0.0");
			   64	
			'''

			# Routing
			ipv4RoutingHelper = ns.Ipv4StaticRoutingHelper()

			serverRouting = ipv4RoutingHelper.GetStaticRouting(remoteHost.GetObject[ns.Ipv4]())
			serverRouting.AddNetworkRouteTo(ns.Ipv4Address("70.0.0.0"),ns.Ipv4Mask("255.0.0.0"), 1)

			
			ues_ids = ueNodes_config[config_i].split(",")
			print(serverNodes[config_i],"--LTE-->",ues_ids)

			# Létrehozzuk az eNodeB + UE node-okat
			for ue_id in ues_ids:
				enbNodes = ns.NodeContainer()
				enbNodes.Create(1)

				ueNodes = ns.NodeContainer()
				ueNodes.Add(nodes.Get(int(ue_id)))

				# Mobilitás (fix pozíciók)
				positionAlloc = ns.CreateObject[ns.ListPositionAllocator]()
				positionAlloc.Add(ns.Vector(2, 0, 0));
					
				mobility = ns.MobilityHelper()
				mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel")
				mobility.SetPositionAllocator(positionAlloc);
				mobility.Install(ueNodes)
				mobility.Install(enbNodes)

				# LTE eszközök
				enbLteDevs = lteHelper.InstallEnbDevice(enbNodes)
				ueLteDevs = lteHelper.InstallUeDevice(ueNodes)

				# Internet stack az UE-re
				internet = ns.InternetStackHelper()
				internet.Install(ueNodes)
				ueIpIface = epcHelper.AssignUeIpv4Address(ns.NetDeviceContainer(ueLteDevs))
				interfaces[int(ue_id)] = [ueIpIface.GetAddress(0)]
				
				# Assign IP address to UEs
				ueRouting = ipv4RoutingHelper.GetStaticRouting(ueNodes.Get(0).GetObject[ns.Ipv4]())
				ueRouting.SetDefaultRoute(epcHelper.GetUeDefaultGatewayAddress(),1)

				# UE attach
				lteHelper.Attach(ueLteDevs.Get(0), enbLteDevs.Get(0))

				# Activate a data radio bearer
				# bearer =	ns.EpsBearer(ns.EpsBearer.GBR_CONV_VOICE)
				# lteHelper.ActivateDedicatedEpsBearer (ueLteDevs, bearer, ns.EpcTft.Default())
				# lteHelper.ActivateDataRadioBearer (ueLteDevs, bearer)
		print("LTE configured")



	if '5GNR' in conf:

		# -------------- 5GNR -------------------
		serverNodes = conf['5GNR']['serverNodes'].split(";")
		ueNodes_config = conf['5GNR']['UEs'].split(";")
		randomStream = 1


		ueNetDevAndIf = {}

		# ez a jonak levo megoldas
		for config_i in range(len(serverNodes)):
			if not serverNodes[config_i]:
				continue

			print(serverNodes[config_i],"--5G NR-->",ueNodes_config[config_i].split(","))

			useUdp = True
			numerology = 1
			if 'numerology' in conf['5GNR']:
				numerology = int(conf['5GNR']['numerology'])
			txPower = 41
			

			# setup the nr simulation
			nrHelper =	ns.CreateObject[ns.NrHelper]()
			# allBwps = getBwps()
			#----
			# centralFrequency = 4e9
			# bandwidth = 10e6
			centralFrequency = 3.5e9
			if 'centralFrequency' in conf['5GNR']:
				centralFrequency = float(conf['5GNR']['centralFrequency'])
			
			bandwidth = 100e6  # 80-100 Mhz csatornakiosztás a tipikus

			channelHelper = ns.CreateObject[ns.NrChannelHelper]() 
			# Set channel using UMa scenario and LOS channel condition
			channelHelper.ConfigureFactories("UMa", "LOS", "ThreeGpp")
			# simple band configuration and initialize
			ccBwpCreator = ns.CcBwpCreator()
			numCc = 1
			bandConf = ns.CcBwpCreator.SimpleOperationBandConf(centralFrequency, bandwidth, numCc)

			band = ccBwpCreator.CreateOperationBandContiguousCc(bandConf)
			# Set and create channel to this band
			channelHelper.AssignChannelsToBands({band})
			allBwps = ns.CcBwpCreator.GetAllBwps({band})

			nrHelper.SetSchedulerTypeId(ns.TypeId.LookupByName("ns3::NrMacSchedulerOfdmaPF"))
			# nrHelper.SetSchedulerTypeId(ns.TypeId.LookupByName("ns3::NrMacSchedulerOfdmaRR"))
			
			nrHelper.SetGnbPhyAttribute("TxPower", ns.DoubleValue(txPower))
			nrHelper.SetGnbPhyAttribute("Numerology", ns.UintegerValue(numerology))
			nrHelper.SetGnbPhyAttribute("NoiseFigure", ns.DoubleValue(5))
			nrHelper.SetUePhyAttribute("TxPower", ns.DoubleValue(23))
			nrHelper.SetUePhyAttribute("NoiseFigure", ns.DoubleValue(7))

			# ns.Config.SetDefault("ns3::NrRlcUm::MaxTxBufferSize", ns.UintegerValue(999999999))
			ns.Config.SetDefault("ns3::NrRlcUm::MaxTxBufferSize", ns.UintegerValue(2000000))

			# rlc_mode = ns.NrGnbRrc.RLC_UM_ALWAYS if useUdp else ns.NrGnbRrc.RLC_AM_ALWAYS
			# ns.Config.SetDefault("ns3::NrGnbRrc::EpsBearerToRlcMapping", ns.EnumValue(rlc_mode))

			ns.cppyy.gbl.SetEpsBearerToRlcMapping(useUdp)

			nrHelper.SetGnbAntennaAttribute("NumRows", ns.UintegerValue(8))	
			nrHelper.SetGnbAntennaAttribute("NumColumns", ns.UintegerValue(8))
			nrHelper.SetGnbAntennaAttribute("AntennaElement",
											 ns.PointerValue(ns.CreateObject[ns.ThreeGppAntennaModel]()))
			nrHelper.SetGnbAntennaAttribute("AntennaHorizontalSpacing", ns.DoubleValue(0.5))
			nrHelper.SetGnbAntennaAttribute("AntennaVerticalSpacing", ns.DoubleValue(0.8))
			nrHelper.SetGnbAntennaAttribute("DowntiltAngle", ns.DoubleValue(0 * math.pi / 180.0))
			nrHelper.SetUeAntennaAttribute("NumRows", ns.UintegerValue(1))
			nrHelper.SetUeAntennaAttribute("NumColumns", ns.UintegerValue(1))
			nrHelper.SetUeAntennaAttribute("AntennaElement",
											ns.PointerValue(ns.CreateObject[ns.IsotropicAntennaModel]()))
											
			# Beamforming method
			idealBeamformingHelper = ns.CreateObject[ns.IdealBeamformingHelper]()
			idealBeamformingHelper.SetAttribute("BeamformingMethod",
												 ns.TypeIdValue(ns.DirectPathBeamforming.GetTypeId()))
			nrHelper.SetBeamformingHelper(idealBeamformingHelper)
			
			ns.Ipv4AddressGenerator.Reset()
			ns.Ipv4AddressGenerator.Init(ns.Ipv4Address(str(70+config_i)+".0.0.0"), ns.Ipv4Mask("255.0.0.0"))

			nrEpcHelper = ns.CreateObject[ns.NrPointToPointEpcHelper]()
			# nrEpcHelper.m_ueAddress = ns.Ipv4Address("70.0.0.0")
			# nrEpcHelper.m_ueMask    = ns.Ipv4Mask("255.0.0.0")
			
			nrHelper.SetEpcHelper(nrEpcHelper)
			nrEpcHelper.SetAttribute("S1uLinkDelay", ns.TimeValue(ns.MilliSeconds(0)))
			# nrEpcHelper.SetAttribute("S1uLinkNetwork", ns.StringValue("77.0.0.0"))


			serverNode = int(serverNodes[config_i])

			gNbNodes = ns.NodeContainer()
			ueNodes = ns.NodeContainer()

			mobility = ns.MobilityHelper()
			mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel")

			gNbHeight = 25
			ueHeight = 1.5

			# gNbNodes.Add(nodes.Get(serverNode))
			gNbNodes.Create(1)
			# ueNodes.Create(arUeNum + vrUeNum + cgUeNum)
			
			# ez kell hogy bekössük a gnb-t mert az nr nem tudja ezt
			#-----------
			csma = ns.CsmaHelper()
			csma.SetChannelAttribute("DataRate", ns.StringValue("1000Gbps"))
			csma.SetChannelAttribute("Delay", ns.TimeValue(ns.NanoSeconds(10)))
			
			tmp_nodecontainer = ns.NodeContainer()
			tmp_nodecontainer.Add(gNbNodes.Get(0))
			tmp_nodecontainer.Add(nodes.Get(serverNode))

			devices = csma.Install(tmp_nodecontainer)
			internet = ns.InternetStackHelper()

			internet.Install(gNbNodes)

			address = ns.Ipv4AddressHelper()
			address.SetBase("10.200.0.0", "255.255.255.0")
			gNbEthIface = address.Assign(devices)
			
			#-----------

			
			for ue_id in ueNodes_config[config_i].split(","):
				ueNodes.Add(nodes.Get(int(ue_id)))


			bsPositionAlloc = ns.CreateObject[ns.ListPositionAllocator]()
			bsPositionAlloc.Add(ns.Vector(0.0, 0.0, gNbHeight))
			mobility.SetPositionAllocator(bsPositionAlloc)
			mobility.Install(gNbNodes)
			pos = gNbNodes.Get(0).GetObject[ns.MobilityModel]().GetPosition()
			print(f"GNB {serverNode} position: x={pos.x}, y={pos.y}, z={pos.z}")

			ueDiscPositionAlloc = ns.CreateObject[ns.RandomDiscPositionAllocator]()
			ueDiscPositionAlloc.SetX(0.0)
			ueDiscPositionAlloc.SetY(0.0)
			rhoRv = ns.CreateObject[ns.UniformRandomVariable]()
			rhoRv.SetAttribute("Min", ns.DoubleValue(10.0))
			rhoRv.SetAttribute("Max", ns.DoubleValue(50.0))
			ueDiscPositionAlloc.SetRho(rhoRv)
			ueDiscPositionAlloc.SetZ(ueHeight)
			mobility.SetPositionAllocator(ueDiscPositionAlloc)

			ueContainer = ns.NodeContainer()
			for i in range(ueNodes.GetN()):
				mobility.Install(ueNodes.Get(i));
				ueContainer.Add(ueNodes.Get(i))
				
			ueIds = ueNodes_config[config_i].split(",")
			for i in range(ueNodes.GetN()):
				node = ueNodes.Get(i)
				mob = node.GetObject[ns.MobilityModel]()
				pos = mob.GetPosition()
				print(f"UE {ueIds[i]} position: x={pos.x}, y={pos.y}, z={pos.z}")

			# ns.Ipv4AddressGenerator.Reset()
			# ns.Ipv4AddressGenerator.Init(ns.Ipv4Address(str(70+config_i)+".0.0.0"), ns.Ipv4Mask("255.0.0.0"))

			gNbNetDev = nrHelper.InstallGnbDevice(gNbNodes, allBwps)

			ueNetDev = nrHelper.InstallUeDevice(ueContainer, allBwps)
			# ez a random seed vegulis. minde ue-nak gnb-nek sajat kell, hogy ne szinkronizalodjanak, de reprodukalhato legyen
			# randomStream = 1;
			randomStream += nrHelper.AssignStreams(ueNetDev, randomStream);

			internet = ns.InternetStackHelper()
			internet.Install(ueNodes)
			
			# Assign IP address to UEs
			ipv4RoutingHelper = ns.Ipv4StaticRoutingHelper()

			for i in range(ueNodes.GetN()):
				ueRouting = ipv4RoutingHelper.GetStaticRouting(ueNodes.Get(i).GetObject[ns.Ipv4]())
				ueRouting.SetDefaultRoute(nrEpcHelper.GetUeDefaultGatewayAddress(),1)
			
			ueIpIface = ns.Ipv4InterfaceContainer()

			ueIpIface = nrEpcHelper.AssignUeIpv4Address(ns.NetDeviceContainer(ueNetDev))
			
			ue_ids = ueNodes_config[config_i].split(",")
			for i in range(ueNodes.GetN()):
				ue_id = int(ue_ids[i])
				if ue_id in ueNetDevAndIf:
					print("UE already connected to an other gnodeb")
					sys.exit(1)
				ueNetDevAndIf[ue_id] = {"netdev":ueNetDev.Get(i), "if":ueIpIface.Get(i)}

			# attach UEs to the closest gNB
			nrHelper.AttachToClosestGnb(ueNetDev, gNbNetDev)
			
		print("5GNR configured")

	# ns.Ipv4GlobalRoutingHelper.PopulateRoutingTables()

	x = CollectLinkInterfaces()
	BuildRouting(x)




	appDuration = 2000
	appStartTimeMs = 400
	arDataRate = 5	# Mbps
	vrDataRate = 30 # Mbps
	cgDataRate = 20 # Mbps
	arFps = 30
	vrFps = 60
	cgFps = 60
	isMx1 = True

	arTfts = cppyy.gbl.std.vector(ns.NrEpcTft)()
	
	UEhasBearer = list()


	if '5Gtraffic' in conf:
		i = -1
		for link in conf['5Gtraffic']['ARtraffic'].split(","):
			if not link:
				continue
			i += 1
			srcId, dstId = map(int,link.split("-"))
			print(srcId,"--5G traffic XR-->",dstId)
			
			srcHost = nodes.Get(srcId)
			dstHost = nodes.Get(dstId)
			
			src_ipv4 = srcHost.GetObject[ns.Ipv4]()
			srcHostAddr = src_ipv4.GetAddress(1, 0).GetLocal()
			
			ueArContainer = ns.NodeContainer()
			ueArContainer.Add(dstHost)

			# create the internet and install the IP stack on the UEs
			# get SGW/PGW and create a single RemoteHost
			remoteHost, remoteHostIpv4Address = nrEpcHelper.SetupRemoteHost("100Gb/s", 1000, ns.Seconds(0.000),f"{200+i}.0.0.0")
			# remoteHostContainer = ns.NodeContainer(remoteHost)
			# remoteHost, remoteHostIpv4Address = srcHost, srcHostAddr
			remoteHostContainer = ns.NodeContainer(remoteHost)

			# Install sink application
			serverApps = ns.ApplicationContainer()

			# configure the transport protocol to be used
			transportProtocol = "ns3::UdpSocketFactory" if useUdp else "ns3::TcpSocketFactory"
			dlPortArStart = 1001+(i*3) # AR has 3 flows
			dlPortArStop = 1004+(i*3)

			# The bearer that will carry AR traffic
			arBearer = ns.NrEpsBearer(ns.NrEpsBearer.NGBR_LOW_LAT_EMBB)
			arTft = ns.Create[ns.NrEpcTft]()
			dlpfAr = ns.NrEpcTft.PacketFilter() 

			dlpfAr.localPortStart = dlPortArStart
			dlpfAr.localPortEnd = dlPortArStop
			arTft.Add(dlpfAr)
			
			# Install traffic generators
			clientApps = ns.ApplicationContainer()
			pingApps = ns.ApplicationContainer()

			#ide kellene valahogy athozni a IpIface adatokat és netdev adatokat azokrol a ue-krol
			
			ueArIpIface = ns.Ipv4InterfaceContainer()
			ueArNetDev = ns.NetDeviceContainer()

			ueArNetDev.Add(ueNetDevAndIf[dstId]['netdev'])
			ueArIpIface.Add(ueNetDevAndIf[dstId]['if'])

			if ueNetDevAndIf[dstId]['netdev'] in UEhasBearer:
				needBearer = False

			UEhasBearer.append(ueNetDevAndIf[dstId]['netdev'])
			
			ConfigureXrApp(ueArContainer,
							   0,		 # ez mondja meg melyik ue-rol van szo
							   ueArIpIface,
							   ns.AR_M3,
							   arDataRate,
							   arFps,
							   dlPortArStart,
							   transportProtocol,
							   remoteHostContainer,
							   ueArNetDev,
							   nrHelper,
							   arBearer,
							   arTft,
							   isMx1,
							   arTfts,
							   serverApps,
							   clientApps,
							   pingApps,
							   needBearer);
							   
			pingApps.Start(ns.Seconds(2.0))
			pingApps.Stop(ns.Seconds(3.0))

			# start server and client apps
			serverApps.Start(ns.Seconds(2.0))
			clientApps.Start(ns.Seconds(3.0))
			serverApps.Stop(ns.Seconds(40.0))
			clientApps.Stop(ns.Seconds(40.0))

			servers.append((str(dstId)+"(XR)",serverApps))



			

		i = -1
		remoteHostObjects = {}
		vrdatarates = list(map(int,conf['5Gtraffic']['VRDataRate'].split(",")))
		# TODO: Ez most teszt jelleggel, hogy csak 1x jojjon letre a remoteHost
		needBearer = True
		
		for link in conf['5Gtraffic']['VRtraffic'].split(","):
			if not link:
				continue
			i += 1
			srcId, dstId = map(int,link.split("-"))
			print(srcId,"--5G traffic VR-->",dstId)
			
			srcHost = nodes.Get(srcId)
			dstHost = nodes.Get(dstId)
			
			src_ipv4 = srcHost.GetObject[ns.Ipv4]()
			# dst_ipv4 = dstHost.GetObject[ns.Ipv4]()
			srcHostAddr = src_ipv4.GetAddress(1, 0).GetLocal()
			# dstHostAddr = dst_ipv4.GetAddress(1, 0).GetLocal()
			
			ueVrContainer = ns.NodeContainer()
			ueVrContainer.Add(dstHost)

			# create the internet and install the IP stack on the UEs
			# get SGW/PGW and create a single RemoteHost
			# remoteHost, remoteHostIpv4Address = nrEpcHelper.SetupRemoteHost("100Gb/s", 1000, ns.Seconds(0.000),f"{210+i}.0.0.0")
			remoteHost, remoteHostIpv4Address = srcHost, srcHostAddr
			remoteHostContainer = ns.NodeContainer(remoteHost)
			# The bearer that will carry VR traffic
			vrBearer = ns.NrEpsBearer(ns.NrEpsBearer.NGBR_LOW_LAT_EMBB)
			# vrBearer = ns.NrEpsBearer(ns.NrEpsBearer.GBR_CONV_VOICE)

			# Install sink application
			serverApps = ns.ApplicationContainer()

			# configure the transport protocol to be used
			transportProtocol = "ns3::UdpSocketFactory" if useUdp else "ns3::TcpSocketFactory"
			dlPortVrStart = 2001+i

			vrTft = ns.Create[ns.NrEpcTft]()
			ulpfVr = ns.NrEpcTft.PacketFilter()
			# dlpfVr.localPortStart = dlPortVrStart
			ulpfVr.remotePortStart = dlPortVrStart
			# dlpfVr.localPortEnd = dlPortVrStart
			ulpfVr.remotePortEnd = dlPortVrStart
			vrTft.Add(ulpfVr)
			
			# Install traffic generators
			clientApps = ns.ApplicationContainer()
			pingApps = ns.ApplicationContainer()

			ueVrNetDev = ns.NetDeviceContainer()
			ueVrIpIface = ns.Ipv4InterfaceContainer()

			# ueVrNetDev.Add(ueNetDevAndIf[dstId]['netdev'])
			# ueVrIpIface.Add(ueNetDevAndIf[dstId]['if'])
			
			# if ueNetDevAndIf[dstId]['netdev'] in UEhasBearer:
				# needBearer = False

			# UEhasBearer.append(ueNetDevAndIf[dstId]['netdev'])
			ueVrNetDev.Add(ueNetDevAndIf[dstId]['netdev'])
			ueVrIpIface.Add(ueNetDevAndIf[dstId]['if'])
			
			if ueNetDevAndIf[dstId]['netdev'] in UEhasBearer:
				needBearer = False
			else:
				needBearer = True
				UEhasBearer.append(ueNetDevAndIf[dstId]['netdev'])
			
			print(f"-------------------UE {srcId}")
			# ueVrContainer-ben lesz a packet sink, vagyis dst
			# ueVrIpIface - dst ip
			# remoteHostContainer - src
			ConfigureXrApp(ueVrContainer,
						   0,		 # ez mondja meg melyik ue-rol van szo
						   ueVrIpIface,
						   ns.VR_DL1,
						   vrdatarates[i],
						   vrFps,
						   dlPortVrStart,
						   transportProtocol,
						   remoteHostContainer,
						   ueVrNetDev,
						   nrHelper,
						   vrBearer,
						   vrTft,
						   True,
						   arTfts,
						   serverApps,
						   clientApps,
						   pingApps,
						   needBearer);

			pingApps.Start(ns.Seconds(2.0))
			pingApps.Stop(ns.Seconds(3.0))

			# start server and client apps
			serverApps.Start(ns.Seconds(2.0))
			clientApps.Start(ns.Seconds(3.0))
			serverApps.Stop(ns.Seconds(40.0))
			clientApps.Stop(ns.Seconds(40.0))

			servers.append((str(dstId)+"(VR)",serverApps))

		i = -1
		for link in conf['5Gtraffic']['CGtraffic'].split(","):
			if not link:
				continue
			i += 1
			srcId, dstId = map(int,link.split("-"))
			print(srcId,"--5G traffic CG-->",dstId)
			
			srcHost = nodes.Get(srcId)
			dstHost = nodes.Get(dstId)
			
			src_ipv4 = srcHost.GetObject[ns.Ipv4]()
			srcHostAddr = src_ipv4.GetAddress(1, 0).GetLocal()
			
			ueCgContainer = ns.NodeContainer()
			ueCgContainer.Add(dstHost)

			# create the internet and install the IP stack on the UEs
			# get SGW/PGW and create a single RemoteHost
			remoteHost, remoteHostIpv4Address = nrEpcHelper.SetupRemoteHost("100Gb/s", 1000, ns.Seconds(0.000),f"{220+i}.0.0.0")
			# remoteHostContainer = ns.NodeContainer(remoteHost)
			# remoteHost, remoteHostIpv4Address = srcHost, srcHostAddr
			remoteHostContainer = ns.NodeContainer(remoteHost)

			# Install sink application
			serverApps = ns.ApplicationContainer()

			# configure the transport protocol to be used
			transportProtocol = "ns3::UdpSocketFactory" if useUdp else "ns3::TcpSocketFactory"
			dlPortCgStart = 3001+i

			# The bearer that will carry CG traffic
			cgBearer = ns.NrEpsBearer(ns.NrEpsBearer.NGBR_LOW_LAT_EMBB)

			cgTft = ns.Create[ns.NrEpcTft]()
			dlpfCg = ns.NrEpcTft.PacketFilter()
			dlpfCg.localPortStart = dlPortCgStart
			dlpfCg.localPortEnd = dlPortCgStart
			cgTft.Add(dlpfCg)
			
			# Install traffic generators
			clientApps = ns.ApplicationContainer()
			pingApps = ns.ApplicationContainer()

			ueCgNetDev = ns.NetDeviceContainer()
			ueCgIpIface = ns.Ipv4InterfaceContainer()

			ueCgNetDev.Add(ueNetDevAndIf[dstId]['netdev'])
			ueCgIpIface.Add(ueNetDevAndIf[dstId]['if'])

			arTfts = cppyy.gbl.std.vector(ns.NrEpcTft)()

			if ueNetDevAndIf[dstId]['netdev'] in UEhasBearer:
				needBearer = False

			UEhasBearer.append(ueNetDevAndIf[dstId]['netdev'])
			
			ConfigureXrApp(ueCgContainer,
						   0,		 # ez mondja meg melyik ue-rol van szo
						   ueCgIpIface,
						   ns.CG_DL1,
						   cgDataRate,
						   cgFps,
						   dlPortCgStart,
						   transportProtocol,
						   remoteHostContainer,
						   ueCgNetDev,
						   nrHelper,
						   cgBearer,
						   cgTft,
						   True,
						   arTfts,
						   serverApps,
						   clientApps,
						   pingApps,
						   needBearer);
							   
			pingApps.Start(ns.Seconds(2.0))
			pingApps.Stop(ns.Seconds(3.0))

			# start server and client apps
			serverApps.Start(ns.Seconds(2.0))
			clientApps.Start(ns.Seconds(3.0))
			serverApps.Stop(ns.Seconds(40.0))
			clientApps.Stop(ns.Seconds(40.0))

			servers.append((str(dstId)+"(CG)",serverApps))



	# create Camera-->UE
	if 'Camera-to-UE' in conf:
		for link in conf['Camera-to-UE']['traffic'].split(","):
			if not link:
				continue
			srcId, dstId = map(int,link.split("-"))
			print(srcId,"--Camera-to-UE-->",dstId)
			
			srcHost = nodes.Get(srcId)
			dstHost = nodes.Get(dstId)
			
			
			dst_ipv4 = dstHost.GetObject[ns.Ipv4]()
			dstHostAddr = dst_ipv4.GetAddress(1, 0).GetLocal()
			
			dlPort = 12340;
			ulPort = 20000+srcId;
			clientApps = ns.ApplicationContainer()
			serverApps = ns.ApplicationContainer()
			servers.append((f"(Cam->UE) ({srcId}->{dstId})",serverApps))

			# dlPacketSinkHelper =	ns.PacketSinkHelper("ns3::UdpSocketFactory", ns.InetSocketAddress (ns.Ipv4Address.GetAny (), dlPort).ConvertTo())

			# serverApps.Add (dlPacketSinkHelper.Install (ueNodes.Get(0)))

			# dlClient = ns.UdpClientHelper(ns.InetSocketAddress (ueIpIface.GetAddress (0), dlPort).ConvertTo());
			# dlClient.SetAttribute ("Interval", ns.TimeValue (ns.MilliSeconds(2)));
			# dlClient.SetAttribute ("MaxPackets", ns.UintegerValue(100));

			# clientApps.Add (dlClient.Install (remoteHost));

			ulPacketSinkHelper =  ns.PacketSinkHelper("ns3::UdpSocketFactory", ns.InetSocketAddress (ns.Ipv4Address.GetAny (), ulPort).ConvertTo())
			serverApps.Add (ulPacketSinkHelper.Install (dstHost))

			ulClient = ns.UdpClientHelper(ns.InetSocketAddress (dstHostAddr, ulPort).ConvertTo());
			ulClient.SetAttribute ("Interval", ns.TimeValue (ns.MilliSeconds(float(conf['Camera-to-UE']['interval_ms']))));
			ulClient.SetAttribute ("MaxPackets", ns.UintegerValue(int(conf['Camera-to-UE']['max_packet'])));
			ulClient.SetAttribute("PacketSize", ns.UintegerValue(int(conf['Camera-to-UE']['packetsize_byte'])))

			

			clientApps.Add (ulClient.Install (srcHost))
			collectedCameraApps[link] = clientApps.Get(0)

			# Python-ban az ns3-python-bindings kicsit másképp ütemez — a csomagküldés 0.01s-nál hamarabb történhet, mielőtt az LTE bearer teljesen aktiválódik. Ilyenkor a csomag “eltűnik”.
			serverApps.Start (ns.Seconds (0.1));
			clientApps.Start (ns.Seconds (0.2));

	if 'Sensor-to-Server' in conf:
		for link in conf['Sensor-to-Server']['traffic'].split(","):
			if not link:
				continue

			srcId, dstId = map(int,link.split("-"))
			print(srcId,"--Sensor-to-Server-->",dstId)
			
			srcHost = nodes.Get(srcId)
			dstHost = nodes.Get(dstId)

			dst_ipv4 = dstHost.GetObject[ns.Ipv4]()
			dstHostAddr = dst_ipv4.GetAddress(1, 0).GetLocal()

			ulPort = 30000;
			clientApps = ns.ApplicationContainer()
			serverApps = ns.ApplicationContainer()
			servers.append((str(dstId)+"(Sens->Serv)",serverApps))

			ulPacketSinkHelper =  ns.PacketSinkHelper("ns3::UdpSocketFactory", ns.InetSocketAddress (ns.Ipv4Address.GetAny (), ulPort).ConvertTo())
			serverApps.Add (ulPacketSinkHelper.Install (dstHost))

			ulClient = ns.UdpClientHelper(ns.InetSocketAddress (dstHostAddr, ulPort).ConvertTo());
			ulClient.SetAttribute ("Interval", ns.TimeValue (ns.MilliSeconds(float(conf['Sensor-to-Server']['interval_ms']))));
			ulClient.SetAttribute ("MaxPackets", ns.UintegerValue(int(conf['Sensor-to-Server']['max_packet'])));
			ulClient.SetAttribute("PacketSize", ns.UintegerValue(int(conf['Sensor-to-Server']['packetsize_byte'])))


			clientApps.Add (ulClient.Install (srcHost));
			collectedSensorApps[link] = clientApps.Get(0)


			# Python-ban az ns3-python-bindings kicsit másképp ütemez — a csomagküldés 0.01s-nál hamarabb történhet, mielőtt az LTE bearer teljesen aktiválódik. Ilyenkor a csomag “eltűnik”.
			serverApps.Start (ns.Seconds (0.1));
			clientApps.Start (ns.Seconds (0.5));
			
	print("---------------")

	ns.LogComponentEnable("Ipv4L3Protocol", ns.LOG_LEVEL_INFO)

	# kikapcsolva, gyorsabb futás miatt
	# anim = ns.AnimationInterface("xmlToNs3/log/xmlTons3Anim.xml")
	# anim.EnablePacketMetadata(True)
	# útvonal és forgalom trace
	# TODO: ez itt behal az NR modulra
	'''anim.EnableIpv4RouteTracking("xmlToNs3/log/routes.xml",
		ns.Seconds(0.0),	# kezdés
		ns.Seconds(float(conf['DEFAULT']['simTime'])),	 # vég
		ns.Seconds(0.25)	# mintavételi periódus
	)'''

	flowmon_helper = ns.FlowMonitorHelper()
	monitor = flowmon_helper.InstallAll()

	# p2p.EnablePcapAll("xmlToNs3/log/xmlToNS.pcap");

	# ---------- Link Capacity Change ------------

	if 'LinkCapacityChange' in conf:
		for e in conf['LinkCapacityChange']['linkAndCapacity'].split(","):
			if not e:
				continue 
			link, eventTime_s, newCapacity = e.split(";")

			event = ns.cppyy.gbl.pythonMakeEventBW(change_bw, collectedDevices[link].Get(0),int(newCapacity)) #netdevice, kbps 
			ns.Simulator.Schedule(ns.Seconds(float(eventTime_s)), event);
				
	# ---------- App Rate Change ------------

		

	if 'AppRateChange' in conf:
		for e in conf['AppRateChange']['cameraApp'].split(","):
			if not e:
				continue 
			link, eventTime_s, newInterval_ms = e.split(";")
			
			event = ns.cppyy.gbl.pythonMakeEventApp(change_app_rate, collectedCameraApps[link], float(newInterval_ms)) #app pointer, interval
			ns.Simulator.Schedule(ns.Seconds(float(eventTime_s)), event);
			
		for e in conf['AppRateChange']['sensorApp'].split(","):
			if not e:
				continue 
			link, eventTime_s, newInterval_ms = e.split(";")
			
			event = ns.cppyy.gbl.pythonMakeEventApp(change_app_rate, collectedSensorApps[link], float(newInterval_ms)) #app pointer, interval
			ns.Simulator.Schedule(ns.Seconds(float(eventTime_s)), event);

	print("=== IPv4 status check before Run() ===")
	for i in range(ns.NodeList.GetNNodes()):
		node = ns.NodeList.GetNode(i)
		ipv4 = None
		try:
			ipv4 = node.GetObject[ns.Ipv4]()
		except Exception as e:
			ipv4 = None
		print(f"Node {i}: node-object={node}, ipv4 is {'present' if ipv4 else 'MISSING'}")
		if ipv4:
			nifs = ipv4.GetNInterfaces()
			print(f"  Ipv4.GetNInterfaces() = {nifs}")
			for ifidx in range(nifs):
				try:
					addr = ipv4.GetAddress(ifidx, 0).GetLocal()
					print(f"    if {ifidx}: addr = {addr}")
				except Exception as e:
					print(f"    if {ifidx}: cannot get address ({e})")
	print("=== end ipv4 check ===")


	ipv4 = node.GetObject[ns.Ipv4]()

	for i in range(ipv4.GetNInterfaces()):
		dev = ipv4.GetNetDevice(i)
		if dev is None:
			print("** WARNING: Interface", i, "has no NetDevice on node", node.GetId())


	# ---------- Simulator Start -----------
	print("---------- Simulator Start -----------")
	ns.Simulator.Stop(ns.Seconds(float(conf['DEFAULT']['simTime'])))
	ns.Simulator.Run()

	monitor.CheckForLostPackets()
	classifier = flowmon_helper.GetClassifier()

	monitor.SerializeToXmlFile("xmlToNs3/log/flowmon-results.xml", True, True)

	ns.Simulator.Destroy()

	stats = monitor.GetFlowStats()
	
	for i in stats:
		t = classifier.FindFlow(i.first)

		print(f"Flow {i.first} ({t.sourceAddress}:{t.sourcePort} . {t.destinationAddress}:{ t.destinationPort}")
		print(f"	Tx Packets: {i.second.txPackets}")
		print(f"	Tx Bytes:	{i.second.txBytes}")
		print(f"	Rx Bytes:	{i.second.rxBytes}")		
		
		if i.second.rxPackets > 0:
			# Measure the duration of the flow from receiver's perspective
			rxDuration = i.second.timeLastRxPacket - i.second.timeFirstTxPacket
		
			throughput = ((i.second.rxBytes * 8.0) / rxDuration.GetSeconds()) * 1e-6
			delay = 1000 * i.second.delaySum.GetSeconds() / i.second.rxPackets
			jitter = 1000 * i.second.jitterSum.GetSeconds() / i.second.rxPackets

			print(f"	Throughput: {throughput} Mbps")
			print(f"	Mean delay:	 {delay} ms")
			print(f"	Mean jitter:  {jitter} ms")
		else:
			print(f"	Throughput:	 0 Mbps")
			print(f"	Mean delay:	 0 ms")
			print(f"	Mean jitter: 0 ms")


	# Eredmények
	resp = []
	for server_id, server in servers:
		s = server.Get(0).GetObject[ns.PacketSink]()
		res = f"A szerver ({server_id}) által fogadott byte-ok száma: {s.GetTotalRx()}"
		print(res)
		resp.append(res)
	return resp
	
	
		
if __name__ == '__main__':
    # runSim(True)
	if (len(sys.argv) > 1):
		runSim(True,sys.argv[1])
	else:
		runSim(True)		