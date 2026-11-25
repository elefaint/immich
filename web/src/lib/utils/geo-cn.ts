/**
 * WGS-84 <-> GCJ-02 conversion for Chinese map providers.
 *
 * Photos store GPS coordinates as WGS-84, while Chinese raster tiles (Amap, Baidu)
 * use GCJ-02. Without conversion, markers are offset by roughly 400-600 meters.
 * `gcj2wgs` uses iterative inversion so repeated save/load cycles do not accumulate drift.
 */

const outOfChina = (lng: number, lat: number) =>
  lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271;

const transformLat = (x: number, y: number) => {
  let ret = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
  ret += ((20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2) / 3;
  ret += ((20 * Math.sin(y * Math.PI) + 40 * Math.sin((y / 3) * Math.PI)) * 2) / 3;
  ret += ((160 * Math.sin((y / 12) * Math.PI) + 320 * Math.sin((y * Math.PI) / 30)) * 2) / 3;
  return ret;
};

const transformLon = (x: number, y: number) => {
  let ret = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
  ret += ((20 * Math.sin(6 * x * Math.PI) + 20 * Math.sin(2 * x * Math.PI)) * 2) / 3;
  ret += ((20 * Math.sin(x * Math.PI) + 40 * Math.sin((x / 3) * Math.PI)) * 2) / 3;
  ret += ((150 * Math.sin((x / 12) * Math.PI) + 300 * Math.sin((x / 30) * Math.PI)) * 2) / 3;
  return ret;
};

export const wgs2gcj = (lng: number, lat: number): [number, number] => {
  if (outOfChina(lng, lat)) {
    return [lng, lat];
  }

  let dLat = transformLat(lng - 105, lat - 35);
  let dLng = transformLon(lng - 105, lat - 35);
  const radLat = (lat / 180) * Math.PI;
  let magic = Math.sin(radLat);
  magic = 1 - 0.00669342162296594323 * magic * magic;
  const sqrtMagic = Math.sqrt(magic);

  dLat = (dLat * 180) / (((6378245 * (1 - 0.00669342162296594323)) / (magic * sqrtMagic)) * Math.PI);
  dLng = (dLng * 180) / ((6378245 / sqrtMagic) * Math.cos(radLat) * Math.PI);

  return [lng + dLng, lat + dLat];
};

export const gcj2wgs = (lng: number, lat: number): [number, number] => {
  if (outOfChina(lng, lat)) {
    return [lng, lat];
  }

  let x = lng;
  let y = lat;
  for (let i = 0; i < 4; i++) {
    const [convertedLng, convertedLat] = wgs2gcj(x, y);
    x += lng - convertedLng;
    y += lat - convertedLat;
  }

  return [x, y];
};
