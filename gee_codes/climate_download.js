/*****************************************
全国矿区静态气候背景因子下载
数据源：WorldClim V1 BIO（1960—1990 气候基准期，约 1 km）
输出：Annual_Temperature（°C）、Annual_Precipitation（mm）
注意：本数据不能代表某一研究年份的实际气候；逐年分析请改用 TerraClimate。
******************************************/

var roiAsset = 'users/your_username/your_mining_area';
var exportFolder = 'Mining_Climate';
var exportCrs = null;
var noDataValue = -9999;

var roi = ee.FeatureCollection(roiAsset);
Map.centerObject(roi, 8);
Map.addLayer(
  roi.style({color: 'red', fillColor: '00000000', width: 2}),
  {},
  'Mining Area'
);

var climate = ee.Image('WORLDCLIM/V1/BIO');
var temperature = climate
  .select('bio01')
  .multiply(0.1)
  .rename('Annual_Temperature')
  .clip(roi)
  .toFloat();
var precipitation = climate
  .select('bio12')
  .rename('Annual_Precipitation')
  .clip(roi)
  .toFloat();
var climateImage = temperature.addBands(precipitation).toFloat();

print('Output bands:', climateImage.bandNames());
Map.addLayer(
  temperature,
  {min: -10, max: 30, palette: ['blue', 'cyan', 'green', 'yellow', 'red']},
  'Annual Temperature'
);
Map.addLayer(
  precipitation,
  {min: 0, max: 2000, palette: ['white', 'cyan', 'blue']},
  'Annual Precipitation'
);

var exportOptions = {
  image: climateImage.unmask({value: noDataValue, sameFootprint: false}),
  description: 'Mining_Climate_WorldClim_V1',
  fileNamePrefix: 'Mining_Climate_WorldClim_V1',
  folder: exportFolder,
  region: roi.geometry(),
  scale: 1000,
  maxPixels: 1e13,
  fileFormat: 'GeoTIFF',
  formatOptions: {cloudOptimized: true, noData: noDataValue}
};

if (exportCrs) {
  exportOptions.crs = exportCrs;
}

Export.image.toDrive(exportOptions);
