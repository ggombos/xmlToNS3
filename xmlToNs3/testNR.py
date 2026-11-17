from ns import ns
import math
import cppyy
cppyy.add_include_path("include")
cppyy._cppyy_enable_fast_cache = True

ns.Packet.EnablePrinting()

def ConfigureXrApp(ueContainer,i,ueIpIface,config,appDataRate,appFps,port,transportProtocol,remoteHostContainer,ueNetDev,nrHelper,bearer,tft,isMx1,tfts,serverApps,clientApps,pingApps):
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

	ueDevice = ueNetDev.Get(i)
	# Activate a dedicated bearer for the traffic type per node
	nrHelper.ActivateDedicatedEpsBearer(ueDevice, bearer, tft)
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




def main():
	appDuration = 3000
	appStartTimeMs = 500
	numerology = 0
	arUeNum = 0
	vrUeNum = 50
	cgUeNum = 0
	# centralFrequency = 4e9
	# bandwidth = 10e6
	centralFrequency = 3.5e9
	bandwidth = 100e6	# 80-100 Mhz csatornakiosztás a tipikus
	txPower = 41
	isMx1 = True
	useUdp = True
	arDataRate = 5	# Mbps
	vrDataRate = 30 # Mbps
	cgDataRate = 20 # Mbps
	arFps = 30
	vrFps = 60
	cgFps = 60
	rngRun = 1

	simTimeMs = appStartTimeMs + appDuration + 2000

	# Set simulation run number
	ns.SeedManager.SetRun(rngRun)

	# setup the nr simulation
	nrHelper =	ns.CreateObject[ns.NrHelper]()
	channelHelper = ns.CreateObject[ns.NrChannelHelper]() 
	# Set channel using UMa scenario and LOS channel condition
	channelHelper.ConfigureFactories("UMa", "LOS", "ThreeGpp")
	# simple band configuration and initialize
	ccBwpCreator = ns.CcBwpCreator()
	bandConf = ns.CcBwpCreator.SimpleOperationBandConf(centralFrequency, bandwidth, 1)

	band = ccBwpCreator.CreateOperationBandContiguousCc(bandConf)
	# Set and create channel to this band
	channelHelper.AssignChannelsToBands({band})
	allBwps = ns.CcBwpCreator.GetAllBwps({band})

	nrHelper.SetGnbPhyAttribute("TxPower", ns.DoubleValue(txPower))
	nrHelper.SetGnbPhyAttribute("Numerology", ns.UintegerValue(numerology))
	nrHelper.SetGnbPhyAttribute("NoiseFigure", ns.DoubleValue(5))
	nrHelper.SetUePhyAttribute("TxPower", ns.DoubleValue(23))
	nrHelper.SetUePhyAttribute("NoiseFigure", ns.DoubleValue(7))

	ns.Config.SetDefault("ns3::NrRlcUm::MaxTxBufferSize", ns.UintegerValue(999999999))

	# rlc_mode = ns.NrGnbRrc.RLC_UM_ALWAYS if useUdp else ns.NrGnbRrc.RLC_AM_ALWAYS
	# ns.Config.SetDefault("ns3::NrGnbRrc::EpsBearerToRlcMapping", ns.EnumValue(rlc_mode))

	cppyy.cppdef("""
	#include "ns3/config.h"
	#include "ns3/nr-gnb-rrc.h"
	#include "ns3/core-module.h"

	void SetEpsBearerToRlcMapping(bool useUdp) {
		ns3::Config::SetDefault("ns3::NrGnbRrc::EpsBearerToRlcMapping",
			ns3::EnumValue(useUdp ? ns3::NrGnbRrc::RLC_UM_ALWAYS : ns3::NrGnbRrc::RLC_AM_ALWAYS));
	}
	""")
	ns.cppyy.gbl.SetEpsBearerToRlcMapping(useUdp)

	nrHelper.SetGnbAntennaAttribute("NumRows", ns.UintegerValue(4))
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

	nrEpcHelper = ns.CreateObject[ns.NrPointToPointEpcHelper]()
	nrHelper.SetEpcHelper(nrEpcHelper)
	nrEpcHelper.SetAttribute("S1uLinkDelay", ns.TimeValue(ns.MilliSeconds(0)))
	# nrEpcHelper.SetAttribute("S1uLinkIPv4", ns.StringValue("200.0.0.0"))
	# nrEpcHelper.SetAttribute("S1apLinkIPv4", ns.StringValue("210.0.0.0"))

	gNbNodes = ns.NodeContainer()
	ueNodes = ns.NodeContainer()
	mobility = ns.MobilityHelper()
	mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel")

	gNbHeight = 25
	ueHeight = 1.5

	gNbNodes.Create(1)
	ueNodes.Create(arUeNum + vrUeNum + cgUeNum)

	bsPositionAlloc = ns.CreateObject[ns.ListPositionAllocator]()
	bsPositionAlloc.Add(ns.Vector(0.0, 0.0, gNbHeight))
	mobility.SetPositionAllocator(bsPositionAlloc)
	mobility.Install(gNbNodes)

	ueDiscPositionAlloc = ns.CreateObject[ns.RandomDiscPositionAllocator]()
	ueDiscPositionAlloc.SetX(0.0)
	ueDiscPositionAlloc.SetY(0.0)
	ueDiscPositionAlloc.SetZ(ueHeight)
	mobility.SetPositionAllocator(ueDiscPositionAlloc)

	for i in range(ueNodes.GetN()):
		mobility.Install(ueNodes.Get(i));

	'''
	 * Create various NodeContainer(s) for the different traffic types.
	 * In ueArContainer, ueVrContainer, ueCgContainer, we will put
	 * AR, VR, CG UEs, respectively.'''
	ueArContainer = ns.NodeContainer()
	ueVrContainer = ns.NodeContainer()
	ueCgContainer = ns.NodeContainer()

	for j in range(arUeNum):
		ue = ueNodes.Get(j)
		ueArContainer.Add(ue)
	for j in range(arUeNum,arUeNum + vrUeNum):
		ue = ueNodes.Get(j)
		ueVrContainer.Add(ue)
	for j in range(arUeNum + vrUeNum,arUeNum + vrUeNum + cgUeNum):
		ue = ueNodes.Get(j)
		ueCgContainer.Add(ue)

	gNbNetDev = nrHelper.InstallGnbDevice(gNbNodes, allBwps)
	ueArNetDev = nrHelper.InstallUeDevice(ueArContainer, allBwps)
	ueVrNetDev = nrHelper.InstallUeDevice(ueVrContainer, allBwps)
	ueCgNetDev = nrHelper.InstallUeDevice(ueCgContainer, allBwps)

	randomStream = 1;
	randomStream += nrHelper.AssignStreams(gNbNetDev, randomStream);
	randomStream += nrHelper.AssignStreams(ueArNetDev, randomStream);
	randomStream += nrHelper.AssignStreams(ueVrNetDev, randomStream);
	randomStream += nrHelper.AssignStreams(ueCgNetDev, randomStream);

	# create the internet and install the IP stack on the UEs
	# get SGW/PGW and create a single RemoteHost
	remoteHost, remoteHostIpv4Address = nrEpcHelper.SetupRemoteHost("100Gb/s", 1000, ns.Seconds(0.000))
	remoteHostContainer = ns.NodeContainer(remoteHost)

	internet = ns.InternetStackHelper()
	internet.Install(ueNodes)

	ueArIpIface = ns.Ipv4InterfaceContainer()
	ueVrIpIface = ns.Ipv4InterfaceContainer()
	ueCgIpIface = ns.Ipv4InterfaceContainer()

	ueArIpIface = nrEpcHelper.AssignUeIpv4Address(ns.NetDeviceContainer(ueArNetDev))
	ueVrIpIface = nrEpcHelper.AssignUeIpv4Address(ns.NetDeviceContainer(ueVrNetDev))
	ueCgIpIface = nrEpcHelper.AssignUeIpv4Address(ns.NetDeviceContainer(ueCgNetDev))

	# attach UEs to the closest gNB
	nrHelper.AttachToClosestGnb(ueArNetDev, gNbNetDev)
	nrHelper.AttachToClosestGnb(ueVrNetDev, gNbNetDev)
	nrHelper.AttachToClosestGnb(ueCgNetDev, gNbNetDev)
	
	# Install sink application
	serverApps = ns.ApplicationContainer()

	# configure the transport protocol to be used
	transportProtocol = "ns3::UdpSocketFactory" if useUdp else "ns3::TcpSocketFactory"
	dlPortArStart = 1121 # AR has 3 flows
	dlPortArStop = 1124
	dlPortVrStart = 1131
	dlPortCgStart = 1141
	
	# The bearer that will carry AR traffic
	arBearer = ns.NrEpsBearer(ns.NrEpsBearer.NGBR_LOW_LAT_EMBB)
	arTft = ns.Create[ns.NrEpcTft]()
	dlpfAr = ns.NrEpcTft.PacketFilter() 
	arTfts = cppyy.gbl.std.vector(ns.NrEpcTft)()

	if (isMx1):
		dlpfAr.localPortStart = dlPortArStart
		dlpfAr.localPortEnd = dlPortArStop
		arTft.Add(dlpfAr)
	else:
		# create 3 xrTfts for 1x1 mapping
		for i in range(3):
			tempTft = ns.CreateObject[ns.NrEpcTft]()
			dlpfAr.localPortStart = dlPortArStart + i
			dlpfAr.localPortEnd = dlPortArStart + i
			tempTft.Add(dlpfAr)
			arTfts.emplace_back(tempTft)

	# The bearer that will carry VR traffic
	vrBearer = ns.NrEpsBearer(ns.NrEpsBearer.NGBR_LOW_LAT_EMBB)

	vrTft = ns.Create[ns.NrEpcTft]()
	dlpfVr = ns.NrEpcTft.PacketFilter()
	dlpfVr.localPortStart = dlPortVrStart
	dlpfVr.localPortEnd = dlPortVrStart
	vrTft.Add(dlpfVr)

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
	
	for i in range(ueArContainer.GetN()):
		ConfigureXrApp(ueArContainer,
					   i,
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
					   pingApps);

	# TODO for VR and CG of 2 flows Tfts and isMx1 have to be set. Currently they are
	# hardcoded for 1 flow
	for i in range(ueVrContainer.GetN()):
		ConfigureXrApp(ueVrContainer,
					   i,
					   ueVrIpIface,
					   ns.VR_DL1,
					   vrDataRate,
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
					   pingApps);
	for i in range(ueCgContainer.GetN()):
		ConfigureXrApp(ueCgContainer,
					   i,
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
					   pingApps);
	
	pingApps.Start(ns.MilliSeconds(100))
	pingApps.Stop(ns.MilliSeconds(appStartTimeMs))

	# start server and client apps
	serverApps.Start(ns.MilliSeconds(appStartTimeMs))
	clientApps.Start(ns.MilliSeconds(appStartTimeMs))
	serverApps.Stop(ns.MilliSeconds(simTimeMs))
	clientApps.Stop(ns.MilliSeconds(appStartTimeMs + appDuration))

	flowmonHelper = ns.FlowMonitorHelper()
	endpointNodes = ns.NodeContainer()
	endpointNodes.Add(remoteHost);
	endpointNodes.Add(ueNodes);

	monitor = flowmonHelper.Install(endpointNodes);
	monitor.SetAttribute("DelayBinWidth", ns.DoubleValue(0.0001))
	monitor.SetAttribute("JitterBinWidth", ns.DoubleValue(0.001))
	monitor.SetAttribute("PacketSizeBinWidth", ns.DoubleValue(20))

	ns.Simulator.Stop(ns.MilliSeconds(simTimeMs))
	ns.Simulator.Run();
	
	for i in range(serverApps.GetN()):
		s = serverApps.Get(i).GetObject[ns.PacketSink]()
		res = f"A szerver ({i}) által fogadott byte-ok száma: {s.GetTotalRx()}"
		print(res)
	'''
	# Print per-flow statistics
	monitor.CheckForLostPackets();
	Ptr<Ipv4FlowClassifier> classifier =
		DynamicCast<Ipv4FlowClassifier>(flowmonHelper.GetClassifier());
	FlowMonitor::FlowStatsContainer stats = monitor.GetFlowStats();

	double averageFlowThroughput = 0.0;
	double averageFlowDelay = 0.0;

	for (std::map<FlowId, FlowMonitor::FlowStats>::const_iterator i = stats.begin();
		 i != stats.end();
		 ++i)
	{
		Ipv4FlowClassifier::FiveTuple t = classifier.FindFlow(i.first);
		std::stringstream protoStream;
		protoStream << (uint16_t)t.protocol;
		if (t.protocol == 6)
		{
			protoStream.str("TCP");
		}
		if (t.protocol == 17)
		{
			protoStream.str("UDP");
		}

		Time txDuration = MilliSeconds(appDuration);
		std::cout << "Flow " << i.first << " (" << t.sourceAddress << ":" << t.sourcePort << " . "
				  << t.destinationAddress << ":" << t.destinationPort << ") proto "
				  << protoStream.str() << "\n";
		std::cout << "	Tx Packets: " << i.second.txPackets << "\n";
		std::cout << "	Tx Bytes:	" << i.second.txBytes << "\n";
		std::cout << "	TxOffered:	"
				  << ((i.second.txBytes * 8.0) / txDuration.GetSeconds()) * 1e-6 << " Mbps\n";
		std::cout << "	Rx Bytes:	" << i.second.rxBytes << "\n";

		if (i.second.rxPackets > 0)
		{
			# Measure the duration of the flow from receiver's perspective
			Time rxDuration = i.second.timeLastRxPacket - i.second.timeFirstTxPacket;
			averageFlowThroughput += ((i.second.rxBytes * 8.0) / rxDuration.GetSeconds()) * 1e-6;
			averageFlowDelay += 1000 * i.second.delaySum.GetSeconds() / i.second.rxPackets;

			double throughput = ((i.second.rxBytes * 8.0) / rxDuration.GetSeconds()) * 1e-6;
			double delay = 1000 * i.second.delaySum.GetSeconds() / i.second.rxPackets;
			double jitter = 1000 * i.second.jitterSum.GetSeconds() / i.second.rxPackets;

			std::cout << "	Throughput: " << throughput << " Mbps\n";
			std::cout << "	Mean delay:	 " << delay << " ms\n";
			std::cout << "	Mean jitter:  " << jitter << " ms\n";
		}
		else
		{
			std::cout << "	Throughput:	 0 Mbps\n";
			std::cout << "	Mean delay:	 0 ms\n";
			std::cout << "	Mean upt:  0  Mbps \n";
			std::cout << "	Mean jitter: 0 ms\n";
		}
		std::cout << "	Rx Packets: " << i.second.rxPackets << "\n";
	}

	std::cout << "\n\n	Mean flow throughput: " << averageFlowThroughput / stats.size()
			  << "Mbps \n";
	std::cout << "	Mean flow delay: " << averageFlowDelay / stats.size() << " ms\n";
	'''
	ns.Simulator.Destroy();
	return 0;


if __name__ == "__main__":
	main()