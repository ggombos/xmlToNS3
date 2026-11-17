# -*- coding: utf-8 -*-
from ns import ns

def main():
	ns.LogComponentEnable("UdpClient", ns.LOG_LEVEL_INFO)
	ns.LogComponentEnable("UdpServer", ns.LOG_LEVEL_INFO)

	# --- Node-ok ---
	nodes = ns.NodeContainer()
	nodes.Create(3)
	sensor = nodes.Get(0)
	gateway = nodes.Get(1)
	server = nodes.Get(2)

	# --- Mobilitás ---
	mobility = ns.MobilityHelper()
	positions = ns.ListPositionAllocator()
	positions.Add(ns.Vector(0, 0, 0))	  # Sensor
	positions.Add(ns.Vector(2, 0, 0))	  # Gateway
	positions.Add(ns.Vector(10, 0, 0))	  # Server
	mobility.SetPositionAllocator(positions)
	mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel")
	mobility.Install(nodes)

	# --- "BLE"-ként működő Wi-Fi kapcsolat (kis hatótáv, kis teljesítmény) ---
	wifi = ns.WifiHelper()
	phy = ns.YansWifiPhyHelper()
	channel = ns.YansWifiChannelHelper.Default()
	phy.SetChannel(channel.Create())
	mac = ns.WifiMacHelper()
	ssid = ns.Ssid("BLE-szimulacio")

	# Sensor (STA)
	mac.SetType("ns3::StaWifiMac", "Ssid", ns.SsidValue(ssid))
	staDevice = wifi.Install(phy, mac, sensor)

	# Gateway (AP)
	mac.SetType("ns3::ApWifiMac", "Ssid", ns.SsidValue(ssid))
	apDevice = wifi.Install(phy, mac, gateway)

	# --- Internet stack ---
	stack = ns.InternetStackHelper()
	stack.Install(nodes)

	address = ns.Ipv4AddressHelper()
	address.SetBase(ns.Ipv4Address("10.1.1.0"), ns.Ipv4Mask("255.255.255.0"))
	devices = ns.NetDeviceContainer()
	devices.Add(staDevice)
	devices.Add(apDevice)
	interfaces = address.Assign(devices)

	# Gateway ↔ Server UDP kapcsolat
	p2p = ns.PointToPointHelper()
	p2p.SetDeviceAttribute("DataRate", ns.DataRateValue(ns.DataRate("10Mbps")))
	p2p.SetChannelAttribute("Delay", ns.TimeValue(ns.MilliSeconds(5)))

	gatewayServer = ns.NodeContainer()
	gatewayServer.Add(gateway)
	gatewayServer.Add(server)
	p2pDevices = p2p.Install(gatewayServer)

	address.SetBase(ns.Ipv4Address("10.1.2.0"), ns.Ipv4Mask("255.255.255.0"))
	serverInterfaces = address.Assign(p2pDevices)

	# --- UDP Server (fogadó szerver) ---
	udpServer = ns.UdpServerHelper(4000)
	serverApp = udpServer.Install(server)
	serverApp.Start(ns.Seconds(1.0))
	serverApp.Stop(ns.Seconds(10.0))

	# --- UDP Client (Gateway küldi a szervernek) ---
	udpClient = ns.UdpClientHelper(ns.InetSocketAddress (serverInterfaces.GetAddress(1), 4000).ConvertTo())
	udpClient.SetAttribute("MaxPackets", ns.UintegerValue(10))
	udpClient.SetAttribute("Interval", ns.TimeValue(ns.Seconds(1.0)))
	udpClient.SetAttribute("PacketSize", ns.UintegerValue(64))
	clientApp = udpClient.Install(gateway)
	clientApp.Start(ns.Seconds(2.0))
	clientApp.Stop(ns.Seconds(10.0))


	anim = ns.AnimationInterface("xmlToNs3/log/xmlTons3Anim-bt.xml")
	anim.EnablePacketMetadata(True)
	# útvonal és forgalom trace
	anim.EnableIpv4RouteTracking("xmlToNs3/log/routes-bt.xml",
		ns.Seconds(0.0),	# kezdés
		ns.Seconds(float(2.0)),	 # vég
		ns.Seconds(0.25)	# mintavételi periódus
	)


	# --- Szimuláció futtatása ---
	ns.Simulator.Stop(ns.Seconds(10.0))
	print("Szimuláció indul...")
	ns.Simulator.Run()
	ns.Simulator.Destroy()
	print("Szimuláció vége.")

if __name__ == "__main__":
	main()
