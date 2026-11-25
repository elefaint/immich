/** Default view for the full-screen map page, loaded from /static/map-default.json. */

export interface MapDefaultView {
  enabled: boolean;
  zoom: number;
  center: { lng: number; lat: number };
  zoomReplaceBelow: number;
}

const FALLBACK: MapDefaultView = {
  enabled: true,
  zoom: 11,
  center: { lng: 104.0658, lat: 30.6572 },
  zoomReplaceBelow: 5,
};

const withDefaults = (config: Partial<MapDefaultView> | undefined): MapDefaultView | undefined => {
  if (!config || config.enabled === false) {
    return undefined;
  }

  return { ...FALLBACK, ...config, center: config.center ?? FALLBACK.center };
};

/** Value injected by app.html before the app boots. */
export const getMapDefaultView = (): MapDefaultView | undefined => {
  const config = (globalThis as { __wbMapDefault?: Partial<MapDefaultView> }).__wbMapDefault;
  return withDefaults(config);
};

/** Await this when creating the map so edits to map-default.json take effect without a rebuild. */
export const loadMapDefaultView = async (): Promise<MapDefaultView | undefined> => {
  try {
    const response = await fetch('/map-default.json', { cache: 'no-store' });
    if (response.ok) {
      return withDefaults((await response.json()) as Partial<MapDefaultView>);
    }
  } catch {
    // fall back to the value injected in app.html
  }

  return getMapDefaultView();
};
