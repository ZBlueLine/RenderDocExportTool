import sys
import csv

folderName = "E:/RenderDoc/Export/"
startIndex = 475
endIndex = 759

isPrint = False
# Import renderdoc if not already imported (e.g. in the UI)
if 'renderdoc' not in sys.modules and '_renderdoc' not in sys.modules:
	import renderdoc

# Alias renderdoc for legibility
rd = renderdoc

# We'll need the struct data to read out of bytes objects
import struct
import os

# We base our data on a MeshFormat, but we add some properties
class MeshData(rd.MeshFormat):
	indexOffset = 0
	name = ''

def pySaveTexture(resourceId,eventId,controller):
	texsave = rd.TextureSave()
	texsave.resourceId = resourceId
	if texsave.resourceId == rd.ResourceId.Null():
		return False

	filename = str(int(texsave.resourceId))
	# texsave.alpha = rd.AlphaMapping.BlendToCheckerboard
	# Most formats can only display a single image per file, so we select the
	# first mip and first slice
	texsave.mip = 0
	texsave.slice.sliceIndex = 0
	texsave.alpha = rd.AlphaMapping.Preserve
	texsave.destType = rd.FileType.PNG
	
	if not os.path.exists("{0}/{1}".format(folderName,eventId)):
		os.makedirs("{0}/{1}".format(folderName,eventId))

	outTexPath = "{0}/{1}/{2}.png".format(folderName,eventId,filename)
	controller.SaveTexture(texsave, outTexPath)
	print("Save Texture: {0}".format(outTexPath))
	return True

def findIndexDrawLoop(d,index):
	ret = None
	if d.eventId == index:
		return d
	
	for c in d.children:
		ret = findIndexDrawLoop(c,index)
		if ret:
			return ret
	
	return ret

# Recursively search for the drawcall with the most vertices
def findIndexDraw(index,controller):
	ret = None
	for d in controller.GetDrawcalls():
		if d.eventId == index:
			ret = d
			return ret

		for c in d.children:
			ret = findIndexDrawLoop(c,index)
			if ret:
				return ret	
	return ret

# Unpack a tuple of the given format, from the data
def unpackData(fmt, data):
	if isPrint:
		print(888)
	# We don't handle 'special' formats - typically bit-packed such as 10:10:10:2
	
		# raise RuntimeError("Packed formats are not supported!")

	formatChars = {}
	#                                 012345678
	formatChars[rd.CompType.UInt]  = "xBHxIxxxL"
	formatChars[rd.CompType.SInt]  = "xbhxixxxl"
	formatChars[rd.CompType.Float] = "xxexfxxxd" # only 2, 4 and 8 are valid

	# These types have identical decodes, but we might post-process them
	formatChars[rd.CompType.UNorm] = formatChars[rd.CompType.UInt]
	formatChars[rd.CompType.UScaled] = formatChars[rd.CompType.UInt]
	formatChars[rd.CompType.SNorm] = formatChars[rd.CompType.SInt]
	formatChars[rd.CompType.SScaled] = formatChars[rd.CompType.SInt]

	# We need to fetch compCount components
	vertexFormat = str(fmt.compCount) + formatChars[fmt.compType][fmt.compByteWidth]

	# Unpack the data
	value = struct.unpack_from(vertexFormat, data, 0)

	# If the format needs post-processing such as normalisation, do that now
	if fmt.compType == rd.CompType.UNorm:
		divisor = float((2 ** (fmt.compByteWidth * 8)) - 1)
		value = tuple(float(i) / divisor for i in value)
	elif fmt.compType == rd.CompType.SNorm:
		maxNeg = -float(2 ** (fmt.compByteWidth * 8)) / 2
		divisor = float(-(maxNeg-1))
		value = tuple((float(i) if (i == maxNeg) else (float(i) / divisor)) for i in value)

	# If the format is BGRA, swap the two components
	if fmt.BGRAOrder():
		value = tuple(value[i] for i in [2, 1, 0, 3])

	return value

# Get a list of MeshData objects describing the vertex inputs at this draw
def getMeshInputs(controller, draw):
	state = controller.GetPipelineState()

	# Get the index & vertex buffers, and fixed vertex inputs
	ib = state.GetIBuffer()
	vbs = state.GetVBuffers()
	attrs = state.GetVertexInputs()
	
	sampleList = state.GetReadOnlyResources(renderdoc.ShaderStage.Fragment)
	for sample in sampleList:
		for res in sample.resources:
			print(res.resourceId)
			if not pySaveTexture(res.resourceId,draw.eventId,controller):
				break
	meshInputs = []

	# for i in ib:
	# if isPri:nt	
	# 	print(i)

	# for v in vbs:
	# 	print(v)

	#for attr in attrs:
		# print(attr.name)
		
	for attr in attrs:
		# We don't handle instance attributes
		if attr.perInstance:
			raise RuntimeError("Instanced properties are not supported!")
		
		meshInput = MeshData()
		meshInput.indexResourceId = ib.resourceId # 2646
		meshInput.indexByteOffset = ib.byteOffset # 0
		meshInput.indexByteStride = ib.byteStride # 0
		meshInput.baseVertex = draw.baseVertex # 0
		meshInput.indexOffset = draw.indexOffset # 0
		meshInput.numIndices = draw.numIndices #???? 18

		# If the draw doesn't use an index buffer, don't use it even if bound
		if not (draw.flags & rd.ActionFlags.Indexed):
			meshInput.indexResourceId = rd.ResourceId.Null()

		# The total offset is the attribute offset from the base of the vertex
		meshInput.vertexByteOffset = attr.byteOffset + vbs[attr.vertexBuffer].byteOffset + draw.vertexOffset * vbs[attr.vertexBuffer].byteStride # 0
		meshInput.format = attr.format
		meshInput.vertexResourceId = vbs[attr.vertexBuffer].resourceId # 2645
		meshInput.vertexByteStride = vbs[attr.vertexBuffer].byteStride # 56
		meshInput.name = attr.name

		meshInputs.append(meshInput)

	return meshInputs

def getIndices(controller, mesh):
	# Get the character for the width of index
	indexFormat = 'B'
	if mesh.indexByteStride == 2:
		indexFormat = 'H'
	elif mesh.indexByteStride == 4:
		indexFormat = 'I'

	# Duplicate the format by the number of indices
	indexFormat = str(mesh.numIndices) + indexFormat

	# If we have an index buffer
	if mesh.indexResourceId != rd.ResourceId.Null():
		# Fetch the data
		ibdata = controller.GetBufferData(mesh.indexResourceId, mesh.indexByteOffset, 0)
		# Unpack all the indices, starting from the first index to fetch
		offset = mesh.indexOffset * mesh.indexByteStride
		indices = struct.unpack_from(indexFormat, ibdata, offset)

		# Apply the baseVertex offset
		return [i + mesh.baseVertex for i in indices]
	else:
		# With no index buffer, just generate a range
		return tuple(range(mesh.numIndices))

def printMeshData(controller, meshData,draw):
	if isPrint:
		print(4444)
	indices = getIndices(controller, meshData[0])

	csvArray = []
	fileheader = []

	formatxyzw = [".x",".y",".z",".w"]

	if isPrint:
		print("Mesh configuration:")
	fileheader.append("VTX")
	fileheader.append("IDX")
	for attr in meshData:
		if not attr.format.Special():
			if isPrint:
				print("\t%s:" % attr.name)
			if isPrint:
				print("\t\t- vertex: %s / %d stride" % (attr.vertexResourceId,  attr.vertexByteStride))
			if isPrint:
				print("\t\t- format: %s x %s @ %d" % (attr.format.compType, attr.format.compCount, attr.vertexByteOffset))
			
			headFormat = "{0}{1}"
			for i in range(0,attr.format.compCount):
				newStr = headFormat.format(attr.name,formatxyzw[i])
				fileheader.append(newStr)

	# We'll decode the first three indices making up a triangle
	csvArray.append(fileheader)
	# ??CSV
	if not os.path.exists("{0}/{1}".format(folderName,draw.eventId)):
		os.makedirs("{0}/{1}".format(folderName,draw.eventId))

	outPath = "{0}/{1}/model.csv".format(folderName,draw.eventId)
	csvFile = open(outPath, "w",newline='')
	writer = csv.writer(csvFile)
	
	# ##########################????#############################################
	for inputIter in draw.outputs:
		if not pySaveTexture(inputIter,draw.eventId,controller):
			break
		
	# ##########################????#############################################

	i = 0
	for idx in indices:
	# for i in range(0, 3):
	# 	idx = indices[i]

		indiceArray = []

		
		if isPrint:
			print("Vertex %d is index %d:" % (i, idx))
		indiceArray.append(i)
		indiceArray.append(idx)
		for attr in meshData:
			if not attr.format.Special():
				# This is the data we're reading from. This would be good to cache instead of
				# re-fetching for every attribute for every index
				offset = attr.vertexByteOffset + attr.vertexByteStride * idx
				data = controller.GetBufferData(attr.vertexResourceId, offset, 0)

				# Get the value from the data
				value = unpackData(attr.format, data)
				
				for j in range(0,attr.format.compCount):
					indiceArray.append(value[j])

				# if isPri:ntWe don't go into the details of semantic matching here, just 
				# 	print both
				if isPrint:
					print("\tAttribute '%s': %s" % (attr.name, value))

		csvArray.append(indiceArray)
		i = i + 1

	writer.writerows(csvArray)
	csvFile.close()
	print("??{0}??".format(outPath))

def sampleCodePreDraw(controller,draw):
	if draw.eventId >= startIndex and draw.eventId <= endIndex:
		# Move to that draw
		controller.SetFrameEvent(draw.eventId, True)

		if isPrint:
			print("Decoding mesh inputs at %d: %s\n\n" % (draw.eventId, draw.name))

		# # Calculate the mesh input configuration
		meshInputs = getMeshInputs(controller, draw)
		
		# if isPri:nt# Fetch and 
		# 	print the data from the mesh inputs
		printMeshData(controller, meshInputs,draw)

def sampleCodeRecursion(controller,draw):

	sampleCodePreDraw(controller,draw)
	
	for d in draw.children:
		sampleCodeRecursion(controller,d)

# Recursively search for the drawcall with the most vertices
def biggestDraw(prevBiggest, d):
	ret = prevBiggest
	if ret == None or d.numIndices > ret.numIndices:
		ret = d

	for c in d.children:
		biggest = biggestDraw(ret, c)

		if biggest.numIndices > ret.numIndices:
			ret = biggest

	return ret

def sampleCode(controller):
	##for draw in controller.GetDrawcalls():
	draw = None
	for draw in controller.GetRootActions():
		sampleCodeRecursion(controller,draw)

def loadCapture(filename):
	if isPrint:
		print(222)
	# Open a capture file handle
	cap = rd.OpenCaptureFile()

	# Open a particular file - see also OpenBuffer to load from memory
	status = cap.OpenFile(filename, '', None)

	# Make sure the file opened successfully
	if status != rd.ReplayStatus.Succeeded:
		raise RuntimeError("Couldn't open file: " + str(status))

	# Make sure we can replay
	if not cap.LocalReplaySupport():
		raise RuntimeError("Capture cannot be replayed")

	# Initialise the replay
	status,controller = cap.OpenCapture(rd.ReplayOptions(), None)

	if status != rd.ReplayStatus.Succeeded:
		raise RuntimeError("Couldn't initialise replay: " + str(status))

	return (cap, controller)

if 'pyrenderdoc' in globals():
	if isPrint:
		print(111)
	pyrenderdoc.Replay().BlockInvoke(sampleCode)
else:
	if isPrint:
		print("aaaa")
	rd.InitialiseReplay(rd.GlobalEnvironment(), [])

	if len(sys.argv) <= 1:
		if isPrint:
			print('Usage: python3 {} filename.rdc'.format(sys.argv[0]))
		sys.exit(0)

	cap,controller = loadCapture(sys.argv[1])

	sampleCode(controller)

	controller.Shutdown()
	cap.Shutdown()

	rd.ShutdownReplay()

print("Export complete!")