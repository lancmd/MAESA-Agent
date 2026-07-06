PRO mining_envi_minimum_distance
  COMPILE_OPT idl2

  inputRasterUri = GETENV('MINING_INPUT_RASTER')
  inputVectorUri = GETENV('MINING_TRAINING_VECTOR')
  outputRasterUri = GETENV('MINING_OUTPUT_RASTER')

  IF (inputRasterUri EQ '') OR (inputVectorUri EQ '') OR (outputRasterUri EQ '') THEN $
    MESSAGE, 'Set MINING_INPUT_RASTER, MINING_TRAINING_VECTOR, and MINING_OUTPUT_RASTER.'

  e = ENVI(/HEADLESS)
  inputRaster = e.OpenRaster(inputRasterUri)
  inputVector = e.OpenVector(inputVectorUri)

  statisticsTask = ENVITask('TrainingClassificationStatistics')
  statisticsTask.INPUT_RASTER = inputRaster
  statisticsTask.INPUT_VECTOR = inputVector
  statisticsTask.Execute

  classificationTask = ENVITask('MinimumDistanceClassification')
  classificationTask.INPUT_RASTER = inputRaster
  classificationTask.MEAN = statisticsTask.MEAN
  classificationTask.STDDEV = statisticsTask.STDDEV
  classificationTask.OUTPUT_RASTER_URI = outputRasterUri
  classificationTask.Execute

  e.Close
END
