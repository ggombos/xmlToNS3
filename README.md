INFO:
The script build and run an ns3 simulation based on the config.conf.

REQUIRED: 
ns-allinone-3.45
https://apps.nsnam.org/app/nr/

CONFIG:
1 - COPY contrib/nr to contrib
2 - ./ns3 configure --enable-examples --enable-tests --enable-python-bindings --disable-module=netsimulyzer --enable-module=netanim,nr,point-to-point-layout

RUN:
./ns3 run xmlToNs3/xmlToNs3.py



INSTALL:
 - ns3-3.45 https://www.nsnam.org/releases/ns-allinone-3.45.tar.bz2
 - sudo apt install libc6-dev
 - sudo apt install sqlite3 libsqlite3-dev   # sqlite?
 - sudo apt install libeigen3-dev
 - sudo apt install libboost-dev
 - python3 -m pip install cppyy
 - python3 -m pip install git+https://gitlab.com/cttc-lena/pyttb typing_extensions pybind11 
 - sudo apt install python-is-python3
 - pybind11-config --cmakedir
		# /home/ggombos/.local/lib/python3.11/site-packages/pybind11/share/cmake/pybind11
 -  export CMAKE_PREFIX_PATH="/home/ggombos/.local/lib/python3.11/site-packages/pybind11:$CMAKE_PREFIX_PATH"
 - ./ns3 configure --enable-examples --enable-tests --enable-python-bindings --disable-module=netsimulyzer
 - ./ns3 run --no-build xmlToNs3/xmlToNs3.py
 
HELP:
 - if need some info about a class:
	./ns3 shell
	python
	from ns import ns
	help(ns.LteHelper)