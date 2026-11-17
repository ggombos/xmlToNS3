import xmlToNs3
import sys

# RUN: /ns-3.45$ ./ns3 run xmlToNs3/simWithDifferentUEs.py 1>xmlToNs3/log/run_10_0.log -- 10 0
# plotting: ns-3.45$ python xmlToNs3/plotting.py xmlToNs3/log/run_10_0.log


numberOfUEs = int(sys.argv[1])
percentOfUEsMaxRate = int(sys.argv[2])
freq = sys.argv[3]
numerology = sys.argv[4]
maxRateMbps = 30
minRateMbps = 10

# numNodes=102
# UEs=1,2,3,
# VRtraffic=2-1,
# VRDataRate=10,2,

def getRate(x,y):
	if x>0 and y>0:
		return ",".join([str(maxRateMbps) for i in range(x)])+","+",".join([str(minRateMbps) for i in range(y)])
	elif x>0 and y==0:
		return ",".join([str(maxRateMbps) for i in range(x)])
	else:
		return ",".join([str(minRateMbps) for i in range(y)])

def getTraffic(n):
	return ",".join([f"{i}-1" for i in range(2,n+2)])

outFile = f"xmlToNs3/config/config_{numberOfUEs}UE_{percentOfUEsMaxRate}perc_{numerology}num_{freq}freq.txt"

with open("xmlToNs3/config/config_xUE.txt","r") as inputF, open(outFile,"w") as outputF:
	for l in inputF:
		if l.startswith("UEs="):
			l="UEs="+",".join(list(map(str,range(1,numberOfUEs+2))))+"\n"
		elif l.startswith("numNodes="):
			l="numNodes="+str(numberOfUEs+2)+"\n"
		elif l.startswith("VRtraffic="):
			l="VRtraffic="+getTraffic(numberOfUEs)+"\n"
		elif l.startswith("VRDataRate="):
			l="VRDataRate="+getRate(int((numberOfUEs/100)*percentOfUEsMaxRate), int((numberOfUEs/100)*(100-percentOfUEsMaxRate)))+"\n"
		elif l.startswith("centralFrequency="):
			l="centralFrequency="+freq+"\n"
		elif l.startswith("numerology="):
			l="numerology="+numerology+"\n"
		
		outputF.write(l)

xmlToNs3.runSim(True,outFile)