# -*- python -*-
# -*- coding: utf-8 -*-
#
# michael a.g. aïvázis <michael.aivazis@para-sim.com>
#
# (c) 2013-2018 parasim inc
# (c) 2010-2018 california institute of technology
# all rights reserved
#


# externals
from math import sqrt, pi as π
# the package
import altar
# the analytic implementation of the Mogi source
from .Source import Source as source


# declaration
class Mogi(altar.models.bayesian, family="altar.models.mogi"):
    """
    An implementation of Mogi[1958]

    The surface displacement calculation for a point pressure source in an elastic half space.

    Currently, {mogi} is implemented as a four parameter model: x,y,depth locate the point
    source, and {dV} provides the point source strength as the volume change. It can easily
    become a five parameter model by including the Poisson ratio of the elastic material to the
    list of free parameters.
    """


    # user configurable state
    # parameters
    psets = altar.properties.dict(schema=altar.models.parameters())
    psets.doc = "the model parameter meta-data"

    # data
    observations = altar.properties.int(default=3*(11*11))
    observations.doc = "the number of model degrees of freedom"

    # the norm to use for computing the data log likelihood
    norm = altar.norms.norm()
    norm.default = altar.norms.l2()
    norm.doc = "the norm to use when computing the data log likelihood"

    # the name of the test case
    case = altar.properties.path(default="synthetic")
    case.doc = "the directory with the input files"

    # the file based inputs
    displacements = altar.properties.path(default="displacements.txt")
    displacements.doc = "the name of the file with the displacements"

    stations = altar.properties.path(default="stations.txt")
    stations.doc = "the name of the file with the locations of the observation points"

    # the material properties
    nu = altar.properties.float(default=.25)
    nu.doc = "the Poisson ratio"

    # public data
    parameters = 0 # adjusted during model initialization


    # protocol obligations
    @altar.export
    def initialize(self, application):
        """
        Initialize the state of the model given a {problem} specification
        """
        # chain up
        super().initialize(application=application)

        # compile the parameter layout
        # get the parameter sets
        psets = self.psets
        # initialize the offset
        offset = 0
        # go through my parameter sets
        for name, pset in psets.items():
            # initialize the parameter set
            offset += pset.initialize(model=self, offset=offset)
        # the total number of parameters is now known, so record it
        self.parameters = offset

        # record the layout of the sample vector
        self.xIdx = psets["location"].offset
        self.yIdx = self.xIdx + 1
        self.dIdx = psets["depth"].offset
        self.sIdx = psets["source"].offset

        # mount the directory with my input data
        self.ifs = self.mountInputDataspace(pfs=application.pfs)
        # load the data from the inputs into memory
        self.points, self.d = self.loadInputs()
        # compute the normalization
        self.normalization = self.computeNormalization(observations=self.d.shape)

        # show me
        self.show(job=application.job, channel=self.info)

        # all done
        return self


    @altar.export
    def initializeSample(self, step):
        """
        Fill {step.θ} with an initial random sample from my prior distribution.
        """
        # grab the portion of the sample that's mine
        θ = self.restrict(theta=step.theta)
        # go through each parameter set
        for pset in self.psets.values():
            # and ask each one to {prep} the sample
            pset.initializeSample(theta=θ)
        # and return
        return self


    @altar.export
    def priorLikelihood(self, step):
        """
        Fill {step.prior} with the likelihoods of the samples in {step.theta} in the prior
        distribution
        """
        # grab the portion of the sample that's mine
        θ = self.restrict(theta=step.theta)
        # and the storage for the prior likelihoods
        likelihood = step.prior
        # go through each parameter set
        for pset in self.psets.values():
            # and ask each one to {prep} the sample
            pset.priorLikelihood(theta=θ, priorLLK=likelihood)
        # all done
        return self


    @altar.export
    def dataLikelihood(self, step):
        """
        Fill {step.data} with the likelihoods of the samples in {step.theta} given the available
        data. This is what is usually referred to as the "forward model"
        """
        # get my norm
        norm = self.norm
        # grab the portion of the sample that's mine
        θ = self.restrict(theta=step.theta)
        # the observed displacements
        displacements = self.d
        # the normalization
        normalization = self.normalization
        # and the storage for the data likelihoods
        dataLLK = step.data

        # find out how many samples in the set
        samples = θ.rows
        # get the parameter sets
        psets = self.psets

        # get the offsets of the various parameter sets
        xIdx = self.xIdx
        yIdx = self.yIdx
        dIdx = self.dIdx
        sIdx = self.sIdx

        # get the locations of the observation points
        locations = self.points

        # for each sample in the sample set
        for sample in range(samples):
            # extract the parameters
            parameters = θ.getRow(sample)
            # get the location of the source
            x = parameters[xIdx]
            y = parameters[yIdx]
            # its depth
            d = parameters[dIdx]
            # and its strength; we model the logarithm of this one, so we have to exponentiate
            dV = 10**parameters[sIdx]

            # make a source using the sample parameters
            mogi = source(x=x, y=y, d=d, dV=dV)
            # compute the expected displacement
            u = mogi.displacements(locations=locations)
            # subtract the observed displacements
            u -= displacements
            # compute the norm
            norm = self.norm.eval(v=u)
            # compute its norm, normalize, and store it as the data log likelihood
            dataLLK[sample] = normalization - norm/2

        # all done
        return self


    @altar.export
    def verify(self, step, mask):
        """
        Check whether the samples in {step.theta} are consistent with the model requirements and
        update the {mask}, a vector with zeroes for valid samples and non-zero for invalid ones
        """
        # grab the portion of the sample that's mine
        θ = self.restrict(theta=step.theta)
        # go through each parameter set
        for pset in self.psets.values():
            # and ask each one to verify the sample
            pset.verify(theta=θ, mask=mask)
        # all done; return the rejection map
        return mask


    # implementation details
    def mountInputDataspace(self, pfs):
        """
        Mount the directory with my input files
        """
        # attempt to
        try:
            # mount the directory with my input data
            ifs = altar.filesystem.local(root=self.case)
        # if it fails
        except altar.filesystem.MountPointError as error:
            # grab my error channel
            channel = self.error
            # complain
            channel.log(f"bad case name: '{self.case}'")
            channel.log(str(error))
            # and bail
            raise SystemExit(1)

        # if all goes well, explore it and mount it
        pfs["inputs"] = ifs.discover()
        # all done
        return ifs


    def loadInputs(self):
        """
        Load the data in the input files into memory
        """
        # grab the input dataspace
        ifs = self.ifs

        # first the stations
        try:
            # get the path to the file
            gf = ifs[self.stations]
        # if the file doesn't exist
        except ifs.NotFoundError:
            # grab my error channel
            channel = self.error
            # complain
            channel.log(f"missing station locations: no '{self.stations}' in '{self.case}'")
            # and raise the exception again
            raise
        # if all goes well
        else:
            # prime the locations pile
            points = []
            # open the file
            with gf.open() as stream:
                # grab each line
                for line in stream:
                    # unpack
                    x, y = map(float, line.strip().split(','))
                    # and store
                    points.append((x,y))

        # next, the displacements
        try:
            # get the path to the file
            df = ifs[self.displacements]
        # if the file doesn't exist
        except ifs.NotFoundError:
            # grab my error channel
            channel = self.error
            # complain
            channel.log(f"missing displacements: no '{self.displacements}' in '{self.case}'")
            # and raise the exception again
            raise
        # if all goes well
        else:
            # allocate the vector
            data = altar.vector(shape=self.observations)
            # and load the file contents into memory
            data.load(df.uri)

        # all done
        return points, data


    def computeNormalization(self, observations):
        """
        Compute the normalization of the L2 norm
        """
        # support
        from math import log, pi as π
        # compute and return
        return - log(2*π)*observations / 2;


    def show(self, job, channel):
        """
        Place model information in the supplied {channel}
        """
        # show me
        channel.line("run info:")
        # job
        channel.line(f" -- job: {job}")
        channel.line(f"    hosts: {job.hosts}")
        channel.line(f"    tasks: {job.tasks}")
        channel.line(f"    gpus: {job.gpus}")
        channel.line(f"    chains: {job.chains}")
        # show me the model
        channel.line(f" -- model: {self}")
        # the model state
        channel.line(f"    observations: {self.observations}")
        # the parameter sets
        channel.line(f"    parameters: {self.parameters} total, in {len(self.psets)} sets")

        # go through the parameter sets
        for name, pset in self.psets.items():
            # and show me what we know about them
            channel.line(f"      {name}:")
            channel.line(f"        offset: {pset.offset}:")
            channel.line(f"         count: {pset.count}:")
            channel.line(f"         prior: {pset.prior}:")
            channel.line(f"          prep: {pset.prep}:")

        # the test case name
        channel.line(f" -- case: {self.case}")
        # the contents of the data filesystem
        channel.line(f" -- contents of '{self.case}':")
        channel.line("\n".join(self.ifs.dump(indent=2)))
        # the loaded data
        # the loaded data
        channel.line(f" -- inputs in memory:")
        channel.line(f"    stations: {len(self.points)} locations")
        channel.line(f"    observations: {len(self.d)} displacements")
        # flush
        channel.log()

        # all done
        return self


    # private data
    ifs = None # filesystem with the input data

    # input
    points = None # the list of observation points
    d = None # the matrix of displacements for each control point

    # the sample layout; patched during {initialize}
    xIdx = 0
    yIdx = 0
    dIdx = 0
    sIdx = 0


# end of file
