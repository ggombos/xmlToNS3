import sys
import re
import matplotlib.pyplot as plt


params = {'legend.fontsize': 'x-large',
		'figure.figsize': (6,4),   #6,2
		'axes.labelsize': '24',
		'axes.titlesize':'24',
		'xtick.labelsize':'22',
		'ytick.labelsize':'22',
		'figure.autolayout':False,
		# 'figure.constrained_layout.use':True,
		'text.usetex':True,
		'pdf.fonttype':42,
		'ps.fonttype':42,
		'legend.framealpha':None,
	 }
plt.rcParams.update(plt.rcParamsDefault)
plt.rcParams.update(params)

def parse_log(file_path):
	gnb = None
	ues = []

	pattern = re.compile(r'(GNB|UE)\s+(\d+)\s+position:\s+x=([-\d\.]+),\s*y=([-\d\.]+),\s*z=([-\d\.]+)')

	with open(file_path, 'r') as f:
		for line in f:
			match = pattern.search(line)
			if match:
				device_type = match.group(1)
				UEid = int(match.group(2))
				x = float(match.group(3))
				y = float(match.group(4))
				# z = float(match.group(4))	 # Nem használjuk

				if device_type == "GNB":
					gnb = (x, y)
				elif device_type == "UE":
					ues.append((UEid, x, y))

	return gnb, ues

def plot_positions(gnb, ues, percent, output_file="positions.png"):
	plt.figure(figsize=(8, 8))
	UEid_limit = int((len(ues)*(percent/100.0)))
	print(len(ues),UEid_limit)

	# UE-k
	if ues:
		ue_id, x_ue, y_ue = zip(*ues)
		colors = []
		for _id in ue_id:
			if _id==1:
				colors.append("blue")
			elif _id<=UEid_limit+1:
				colors.append("green")
			else:
				colors.append("red")

		plt.scatter(x_ue[0], y_ue[0], color=colors[0], s=100, label="UE Sink")
			
		if len(x_ue[:UEid_limit])>0:
			plt.scatter(x_ue[1:UEid_limit+1], y_ue[1:UEid_limit+1], color=colors[1:UEid_limit+1], s=100, label="UE 30Mbps")
		if len(x_ue[UEid_limit:])>0:
			plt.scatter(x_ue[UEid_limit+1:], y_ue[UEid_limit+1:], color=colors[UEid_limit+1:], s=100, label="UE 10Mbps")

	# GNB
	if gnb:
		plt.scatter(gnb[0], gnb[1], color="black", s=200, label="GNB")

	# 100 sugarú kör
	circle = plt.Circle((0, 0), 50, color='blue', fill=False, linewidth=3, linestyle="--")
	plt.gca().add_patch(circle)

	plt.axis("equal")
	plt.grid(True)
	plt.legend(loc="upper right")
	# plt.title("GNB és UE pozíciók")
	
	plt.gca().set_xticklabels([])
	plt.gca().set_yticklabels([])

	plt.savefig(output_file[:-4]+".eps", format="eps", dpi=500)
	plt.savefig(output_file, dpi=300)
	plt.close()
	print(f"Kép elmentve: {output_file}")

	
def plot_throughput_from_log(log_file,fl_limit=100, output_file="throughput.png", ax=None, hideYtick=False, freq=None, num=None):
	flow_ids = []
	throughputs = []
	colors=[]

	with open(log_file, "r") as f:
		lines = f.readlines()

	current_flow = None
	flowCount=0
	for line in lines:
		# Flow azonosító sor
		flow_match = re.match(r'Flow\s+(\d+)\s\(70', line)
		if flow_match:
			current_flow = flow_match.group(1)
			flowCount += 1

		c = "green"
		if flowCount<=fl_limit:
			c = "red"
			
		# Throughput sor
		throughput_match = re.search(r'Throughput:\s*([\d\.eE\+\-]+)\s*Mbps', line)
		if throughput_match and current_flow is not None:
			throughput = float(throughput_match.group(1))
			flow_ids.append(f"Flow {current_flow}")
			throughputs.append(throughput)
			colors.append(c)
			current_flow = None	 # hogy ne vegye többször ugyanahhoz a flow-hoz

	if ax is None:
		# Plot
		plt.figure(figsize=(8, 5))
		plt.bar(flow_ids, throughputs, color=colors)
		plt.xlabel("Flow")
		plt.ylabel("Throughput (Mbps)")
		plt.title("Flow Throughput értékek")
		plt.grid(axis="y", linestyle="--", alpha=0.7)

		plt.tight_layout()
		plt.savefig(output_file[:-4]+".eps", format="eps", dpi=500)
		plt.savefig(output_file, dpi=300)
		plt.close()
		print(f"Throughput bar plot elmentve: {output_file}")
	else:
		ax.bar(flow_ids, throughputs, color=colors)
		ax.set_ylim(top=33.0)
		ax.set_xticklabels([])
		ax.hlines(10,-1,10, colors="gray", linestyles="dashed")
		ax.hlines(30,-1,10, colors="gray", linestyles="dashed")
		if not freq is None:
			ax.set_ylabel(freq, fontsize=16)
		if not num is None:
			ax.set_xlabel(num, fontsize=16)



def calc_kpis(log_file, flowcount_limit=100, output_file="kpis.txt"):
	delay_kpi = []
	jitter_kpi = []
	loss_kpi = []
	norm_thr_kpi = []

	with open(log_file, "r") as f:
		lines = f.readlines()

	current_flow = None
	flowCount = 0
	print("Sebesseg be van egetve!! 30 / 10")
	maxMbps = 30.0
	minMbps = 10.0

	# Tx Bytes:	8803974
	# Rx Bytes:	1898122
	# Throughput: 7.493328547293812 Mbps
	# Mean delay:	 150.70841148351647 ms
	# Mean jitter:  10.483331296703296 ms

	tx_bytes = 0.0
	for line in lines:
		# Flow azonosító sor
		flow_match = re.match(r'Flow\s+(\d+)\s\(70', line)
		if flow_match:
			current_flow = flow_match.group(1)
			flowCount+=1

		# Throughput sor
		throughput_match = re.search(r'Throughput:\s*([\d\.eE\+\-]+)\s*Mbps', line)
		if throughput_match and current_flow is not None:
			req_thr = minMbps
			if flowCount<flowcount_limit:
				req_thr = maxMbps
			throughput = (req_thr-float(throughput_match.group(1)))/req_thr
			norm_thr_kpi.append(throughput)
		tx_match = re.search(r'Tx Bytes:\s*([\d\.eE\+\-]+)', line)
		if tx_match and current_flow is not None:
			tx_bytes = float(tx_match.group(1))
		rx_match = re.search(r'Rx Bytes:\s*([\d\.eE\+\-]+)', line)
		if rx_match and current_flow is not None:
			rx_bytes = float(rx_match.group(1))
			loss_kpi.append(tx_bytes-rx_bytes)
			tx_bytes = 0.0
		delay_match = re.search(r'Mean delay:\s*([\d\.eE\+\-]+)\s*ms', line)
		if delay_match and current_flow is not None:
			mean_delay = float(delay_match.group(1))
			delay_kpi.append(mean_delay)
		jitter_match = re.search(r'Mean jitter:\s*([\d\.eE\+\-]+)\s*ms', line)
		if jitter_match and current_flow is not None:
			mean_jitter = float(jitter_match.group(1))
			jitter_kpi.append(mean_jitter)
	
	with open(output_file, "w") as f:
		f.write(f"thr_norm:{sum(norm_thr_kpi) / float(len(norm_thr_kpi))}\n")
		f.write(f"loss_bytes:{sum(loss_kpi) / float(len(loss_kpi))}\n")
		f.write(f"delay_ms:{sum(delay_kpi) / float(len(delay_kpi))}\n")
		f.write(f"jitter_ms:{sum(jitter_kpi) / float(len(jitter_kpi))}\n")
	print(f"KPI file: {output_file}")

def thrToOnePlot(flowcount_limit, output_file="thrGrid"):
	freq =[ "700e6", "2.1e9", "3.5e9" ]
	numerology=[ "1", "2", "3" ]
	numnode=10
	percent=20
	bfs="200000"

	fig, ax = plt.subplots(3,3, sharey=True, figsize=(6,4))

	for i in range(3):
		yt_hide=False
		f = freq[i]
		f2 = f
		n2 = None
		for j in range(3):
			n = numerology[j]
			if i == 2:
				n2 = n
			inputFile=f"xmlToNs3/log/run_{numnode}_{percent}_{f}_{n}_{bfs}.log"
			plot_throughput_from_log(inputFile,fl_limit=flowcount_limit, ax=ax[i][j], hideYtick=yt_hide, freq=f2, num=n2)
			yt_hide=True
			f2 = None
			
	fig.supxlabel('Numerology',fontsize=18)
	fig.supylabel('Central Frequency [Hz]',fontsize=18)
	plt.tight_layout()
	plt.savefig(output_file+".jpg", dpi=300)
	plt.savefig(output_file+".eps", format='eps', dpi=500)
	plt.close()

def main():
	if len(sys.argv) != 2:
		print("Használat: python plot_positions.py <log_fájl>")
		sys.exit(1)

	log_file = sys.argv[1]
	gnb, ues = parse_log(log_file)

	if not gnb:
		print("Figyelem: Nem található GNB a fájlban.")

	percent = int(log_file.split("_")[2].split(".")[0])
	plot_positions(gnb, ues, percent, log_file[:-4]+"_positions.png")

	flowcount_limit = int((len(ues)*(percent/100.0)))

	plot_throughput_from_log(log_file,fl_limit=flowcount_limit, output_file=log_file[:-4]+"_throughput.png")
	calc_kpis(log_file,flowcount_limit, log_file[:-4]+"kpis.txt")
	thrToOnePlot(flowcount_limit, log_file[:-4]+"_throughputGrid")

if __name__ == "__main__":
	main()