FROM lithopscloud/ibmcf-python-v38

RUN apt-get update \
        # Upgrade installed packages to get latest security fixes if the base image does not contain them already.
        && apt-get upgrade -y --no-install-recommends \
        # add some packages required for the pip install
        && apt-get install -y --no-install-recommends \
           wget \
           libssl-dev \
           build-essential \
           cmake \
           pkg-config \
        # cleanup package lists, they are not used anymore in this image
        && rm -rf /var/lib/apt/lists/* \
        && apt-cache search linux-headers-generic

#Upgrade cmake
RUN wget https://github.com/Kitware/CMake/releases/download/v3.19.3/cmake-3.19.3.tar.gz \
	&& tar -xvzf cmake-3.19.3.tar.gz \
	&& cd cmake-3.19.3 \
	&& ./configure \
	&& make \
	&& make install

#install open-mpi
RUN wget https://download.open-mpi.org/release/open-mpi/v4.1/openmpi-4.1.0.tar.gz \
	&& gunzip -c openmpi-4.1.0.tar.gz | tar xf - \
	&& cd openmpi-4.1.0 \
	&& ./configure --prefix=/usr/local \
	&& make all install \
	&& ldconfig

#install GROMACS
#	make check 
RUN wget http://ftp.gromacs.org/pub/gromacs/gromacs-2020.5.tar.gz\
	&& tar xfz gromacs-2020.5.tar.gz \ 
	&& cd gromacs-2020.5 \
	&& mkdir build \
	&& cd build \
	&& cmake .. -DGMX_BUILD_OWN_FFTW=ON -DREGRESSIONTEST_DOWNLOAD=OFF \
	&& make \
	&& make install \
	&& /bin/dash /usr/local/gromacs/bin/GMXRC

RUN cd gromacs-2020.5 \
	&& rm -R -f build \
	&& mkdir build \
	&& cd build \
	&& cmake .. -DGMX_BUILD_OWN_FFTW=ON -DREGRESSIONTEST_DOWNLOAD=OFF -DCMAKE_C_COMPILER=mpicc -DCMAKE_CXX_COMPILER=mpicxx -DGMX_MPI=on \
	&& make \
	&& make install \
	&& /bin/dash /usr/local/gromacs/bin/GMXRC

#RUN export PATH=$PATH:/usr/local/gromax/bin:

#delete old files
RUN rm openmpi-4.1.0.tar.gz && rm gromacs-2020.5.tar.gz && rm cmake-3.19.3.tar.gz
