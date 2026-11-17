from ns import ns

ns.Packet.EnablePrinting()


# ns.cppyy.cppdef("""
		# using namespace ns3;

		# Callback<void,Ptr<const Packet>,const Address&,const Address&>
		# make_sinktrace_callback2(void(*func)(Ptr<const Packet>, const Address&,const Address&))
		# {
			# return MakeCallback(func);
		# }
	# """)

		
# def SinkTracer(packet: ns.Packet, src_address: ns.Address, dst_address: ns.Address) -> None:
	# print(f"At {ns.Simulator.Now().GetSeconds():.0f}s, '{dst_address}' received packet"
		  # f" with {packet.__deref__().GetSerializedSize()} bytes from '{src_address}'")


'''
Server <--> eNodb <--> UE
	10.0.0.0		7.0.0.0
	100Gb/s
'''

def main():

	# sinkTraceCallback = ns.cppyy.gbl.make_sinktrace_callback(SinkTracer)
	
	# LTE + EPC
	lteHelper = ns.CreateObject[ns.LteHelper]()
	# epcHelper = ns.PointToPointEpcHelper()
	# CreateObject-tel kell különben az epcHelper->GetPgwNode() visszaad egy részben inicializált objektumot, ami miatt a PGW-höz kapcsolt interface routingja hiányos lehet.
	epcHelper = ns.CreateObject[ns.PointToPointEpcHelper]()
	lteHelper.SetEpcHelper(epcHelper)

	pgw = epcHelper.GetPgwNode()


	# szerver node
	nodes = ns.NodeContainer()
	nodes.Create(1)
	remoteHost = nodes.Get(0)

	# Internet stack
	internet = ns.InternetStackHelper()
	internet.Install(nodes)


	# PGW <-> szerver node: point-to-point
	p2p = ns.PointToPointHelper()
	p2p.SetDeviceAttribute("DataRate", ns.StringValue("100Gb/s"))
	p2p.SetChannelAttribute("Delay", ns.StringValue("2ms"))
	p2pDevices = p2p.Install(pgw, remoteHost)

	ipv4h = ns.Ipv4AddressHelper()
	ipv4h.SetBase(ns.Ipv4Address("1.0.0.0"), ns.Ipv4Mask("255.0.0.0"))
	internetIpIfaces = ipv4h.Assign(p2pDevices)
	# interface 0 is localhost, 1 is the p2p device
	remoteHostAddr = internetIpIfaces.GetAddress(1)
	
	'''
  // since we use point-to-point links for all S1-U links, 
   56   // we use a /30 subnet which can hold exactly two addresses 
   57   // (remember that net broadcast and null address are not valid)
   58   m_s1uIpv4AddressHelper.SetBase ("10.0.0.0", "255.255.255.252");
   59 
   60   m_x2Ipv4AddressHelper.SetBase ("12.0.0.0", "255.255.255.252");
   61 
   62   // we use a /8 net for all UEs
   63   m_ueAddressHelper.SetBase ("7.0.0.0", "255.0.0.0");
   64   
	'''

	print("------------",1)
	# Routing
	ipv4RoutingHelper = ns.Ipv4StaticRoutingHelper()

	serverRouting = ipv4RoutingHelper.GetStaticRouting(remoteHost.GetObject[ns.Ipv4]())
	serverRouting.AddNetworkRouteTo(ns.Ipv4Address("7.0.0.0"),ns.Ipv4Mask("255.0.0.0"),	1)
	# serverRouting.SetDefaultRoute(internetIpIfaces.GetAddress(0),1)

	# Létrehozzuk az eNodeB + UE node-okat
	ueNodes = ns.NodeContainer()
	enbNodes = ns.NodeContainer()
	ueNodes.Create(1)
	enbNodes.Create(1)
	print("------------",2)

	# Mobilitás (fix pozíciók)
	positionAlloc = ns.CreateObject[ns.ListPositionAllocator]()
	positionAlloc.Add(ns.Vector(10, 0, 0));
	
	mobility = ns.MobilityHelper()
	mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel")
	mobility.SetPositionAllocator(positionAlloc);
	print("------------",2.1)
	mobility.Install(ueNodes)
	print("------------",2.2)
	mobility.Install(enbNodes)
	print("------------",2.3)

	# LTE eszközök
	enbLteDevs = lteHelper.InstallEnbDevice(enbNodes)
	print("------------",2.4)
	ueLteDevs = lteHelper.InstallUeDevice(ueNodes)
	print("------------",3)

	# Internet stack az UE-re
	internet.Install(ueNodes)
	ueIpIface = epcHelper.AssignUeIpv4Address(ns.NetDeviceContainer(ueLteDevs))
	
	# Assign IP address to UEs, and install applications
	ueRouting = ipv4RoutingHelper.GetStaticRouting(ueNodes.Get(0).GetObject[ns.Ipv4]())
	ueRouting.SetDefaultRoute(epcHelper.GetUeDefaultGatewayAddress(),1)

	# UE attach
	lteHelper.Attach(ueLteDevs.Get(0), enbLteDevs.Get(0))
	# lteHelper.Attach(ns.NetDeviceContainer(ueLteDevs))
	print("------------",4)

	# Activate a data radio bearer
	# bearer =  ns.EpsBearer(ns.EpsBearer.GBR_CONV_VOICE)
	# ha kell epc, de ez nem mukodik
	# lteHelper.ActivateDedicatedEpsBearer (ueLteDevs, bearer, ns.EpcTft.Default())
	# lteHelper.ActivateDataRadioBearer (ueLteDevs, bearer)

	dlPort = 12340;
	ulPort = 20000;
	clientApps = ns.ApplicationContainer()
	serverApps = ns.ApplicationContainer()

	# dlPacketSinkHelper =  ns.PacketSinkHelper("ns3::UdpSocketFactory", ns.InetSocketAddress (ns.Ipv4Address.GetAny (), dlPort).ConvertTo())

	# serverApps.Add (dlPacketSinkHelper.Install (ueNodes.Get(0)))

	# dlClient = ns.UdpClientHelper(ns.InetSocketAddress (ueIpIface.GetAddress (0), dlPort).ConvertTo());
	# dlClient.SetAttribute ("Interval", ns.TimeValue (ns.MilliSeconds(2)));
	# dlClient.SetAttribute ("MaxPackets", ns.UintegerValue(100));

	# clientApps.Add (dlClient.Install (remoteHost));

	ulPacketSinkHelper =  ns.PacketSinkHelper("ns3::UdpSocketFactory", ns.InetSocketAddress (ns.Ipv4Address.GetAny (), ulPort).ConvertTo())
	serverApps.Add (ulPacketSinkHelper.Install (remoteHost))

	ulClient = ns.UdpClientHelper(ns.InetSocketAddress (remoteHostAddr, ulPort).ConvertTo());
	ulClient.SetAttribute ("Interval", ns.TimeValue (ns.MilliSeconds(100)));
	ulClient.SetAttribute ("MaxPackets", ns.UintegerValue(1000000));

	clientApps.Add (ulClient.Install (ueNodes.Get(0)));

	# Python-ban az ns3-python-bindings kicsit másképp ütemez — a csomagküldés 0.01s-nál hamarabb történhet, mielőtt az LTE bearer teljesen aktiválódik. Ilyenkor a csomag “eltűnik”.
	serverApps.Start (ns.Seconds (0.1));
	clientApps.Start (ns.Seconds (0.2));

	# clientApps.Get(0).__deref__().TraceConnectWithoutContext("RxWithAddresses", sinkTraceCallback);



	# UDP Server a szerveren
	# port = 12340
	# udpServer = ns.UdpServerHelper(port)
	# serverApps = udpServer.Install(remoteHost)
	# serverApps.Start(ns.Seconds(0.1))
	# serverApps.Stop(ns.Seconds(10.0))

	# UDP Client az UE-n
	# serverIpv4 = remoteHost.GetObject[ns.Ipv4]()
	# serverAddress = serverIpv4.GetAddress(1, 0).GetLocal()
	# udpClient = ns.UdpClientHelper(ns.InetSocketAddress (serverAddress,port).ConvertTo())
	# udpClient.SetAttribute("MaxPackets", ns.UintegerValue(10))
	# udpClient.SetAttribute("Interval", ns.TimeValue(ns.Seconds(0.01)))
	# udpClient.SetAttribute("PacketSize", ns.UintegerValue(1400))

	# clientApps = udpClient.Install(ueNodes.Get(0))
	# clientApps.Start(ns.Seconds(0.5))
	# clientApps.Stop(ns.Seconds(10.0))
	
	print("------------",5)
	
	print("UE IPv4 object:", ueNodes.Get(0).GetObject[ns.Ipv4]())
	print("Server IPv4 object:", remoteHost.GetObject[ns.Ipv4]())
	print("Interfaces count:", internetIpIfaces.GetN())
	print("UE interfaces count:", ueIpIface.GetN())
	
	# ns.Ipv4GlobalRoutingHelper.PopulateRoutingTables()

	print("------------",6)



	flowmon_helper = ns.FlowMonitorHelper()
	monitor = flowmon_helper.InstallAll()

	anim = ns.AnimationInterface("xmlToNs3/log/xmlTons3Anim-testlte.xml")
	anim.EnablePacketMetadata(True)
	anim.EnableIpv4RouteTracking("xmlToNs3/log/routes-testlte.xml",
		ns.Seconds(0.2),    # kezdés
		ns.Seconds(float(2.0)),   # vég
		ns.Seconds(0.25)    # mintavételi periódus
	)

	# lteHelper.EnableLogComponents()
	# ns.LogComponentEnable ("LteUeComponentCarrierManager", ns.LOG_LEVEL_ALL)
	# ns.LogComponentEnable ("LteUeMac", ns.LOG_LEVEL_ALL)
	# ns.LogComponentEnable ("LteUeNetDevice", ns.LOG_LEVEL_ALL)
	# ns.LogComponentEnable ("SimpleUeComponentCarrierManager", ns.LOG_LEVEL_ALL);
	lteHelper.EnableTraces()
	# lteHelper.EnablePdcpTraces()
	p2p.EnablePcapAll("xmlToNs3/log/lena-epc-first.pcap");
	
	# Szimuláció futtatása
	ns.Simulator.Stop(ns.Seconds(2.0))
	ns.Simulator.Run()
	
	monitor.CheckForLostPackets()
	classifier = flowmon_helper.GetClassifier()

	monitor.SerializeToXmlFile("xmlToNs3/log/flowmon-results-testlte.xml", True, True)

	
	ns.Simulator.Destroy()

	# Eredmények
	# server = serverApps.Get(0).GetObject(ns.UdpServer.GetTypeId())
	# print("A szerver által fogadott csomagok száma:", server.GetReceived())

if __name__ == "__main__":
	main()
