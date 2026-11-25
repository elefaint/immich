<script lang="ts" module>
  import { addProtocol, setWorkerUrl, type IControl, type Map as MapLibreMap } from 'maplibre-gl';
  import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
  import { Protocol } from 'pmtiles';

  let protocol = new Protocol();
  setWorkerUrl(workerUrl);
  void addProtocol('pmtiles', protocol.tile);

  // Amap base-layer switcher: street / satellite. The style defines both raster
  // sources up front (amap-street, amap-satellite) plus a lighter annotation
  // layer (amap-note); switching only toggles visibility, so no setStyle reload
  // and no loss of the geojson marker layers.
  type AmapLayerMode = 'street' | 'satellite';
  const AMAP_LAYER_KEY = 'wb_map_layer';

  function getAmapLayerMode(): AmapLayerMode {
    try {
      return localStorage.getItem(AMAP_LAYER_KEY) === 'street' ? 'street' : 'satellite';
    } catch {
      return 'satellite';
    }
  }

  function applyAmapLayer(map: MapLibreMap, mode: AmapLayerMode) {
    try {
      const hasStreet = !!map.getLayer('amap-street');
      const hasSatellite = !!map.getLayer('amap-satellite');
      const hasNote = !!map.getLayer('amap-note');
      if (mode === 'street') {
        if (hasSatellite) map.setLayoutProperty('amap-satellite', 'visibility', 'none');
        if (hasStreet) map.setLayoutProperty('amap-street', 'visibility', 'visible');
        if (hasNote) map.setLayoutProperty('amap-note', 'visibility', 'none');
      } else {
        if (hasStreet) map.setLayoutProperty('amap-street', 'visibility', 'none');
        if (hasSatellite) map.setLayoutProperty('amap-satellite', 'visibility', 'visible');
        if (hasNote) {
          map.setLayoutProperty('amap-note', 'visibility', 'visible');
          map.setPaintProperty('amap-note', 'raster-opacity', 0.55);
        }
      }
    } catch {
      /* style may not be the Amap style; ignore */
    }
  }

  function createAmapLayerControl(): IControl {
    let container: HTMLDivElement;
    let button: HTMLButtonElement;
    const paint = () => {
      const mode = getAmapLayerMode();
      button.textContent = mode === 'satellite' ? '\u{1F6F0}' : '\u{1F5FA}';
      button.title = mode === 'satellite' ? '\u5f53\u524d\uff1a\u536b\u661f\u56fe\uff08\u70b9\u51fb\u5207\u8857\u9053\uff09' : '\u5f53\u524d\uff1a\u8857\u9053\u56fe\uff08\u70b9\u51fb\u5207\u536b\u661f\uff09';
      button.setAttribute('aria-label', '\u5207\u6362\u8857\u9053 / \u536b\u661f\u56fe\u5c42');
    };
    return {
      onAdd(map: MapLibreMap) {
        container = document.createElement('div');
        container.className = 'maplibregl-ctrl';
        container.style.pointerEvents = 'auto';
        button = document.createElement('button');
        button.type = 'button';
        button.style.cssText =
          'pointer-events:auto;width:30px;height:30px;display:flex;align-items:center;justify-content:center;border-radius:6px;border:1px solid rgba(0,0,0,.12);background:rgba(255,255,255,.92);color:#333;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.18);font-size:15px;line-height:1';
        paint();
        button.addEventListener('click', (event) => {
          event.preventDefault();
          event.stopPropagation();
          const next: AmapLayerMode = getAmapLayerMode() === 'satellite' ? 'street' : 'satellite';
          try {
            localStorage.setItem(AMAP_LAYER_KEY, next);
          } catch {
            /* ignore */
          }
          paint();
          applyAmapLayer(map, next);
        });
        container.appendChild(button);
        map.on('styledata', () => applyAmapLayer(map, getAmapLayerMode()));
        applyAmapLayer(map, getAmapLayerMode());
        return container;
      },
      onRemove() {
        container?.remove();
      },
    };
  }
</script>

<script lang="ts">
  import OnEvents from '#lib/components/OnEvents.svelte';
  import { assetViewerManager } from '#lib/managers/asset-viewer-manager.svelte.ts';
  import MapSettingsModal from '#lib/modals/MapSettingsModal.svelte';
  import { createPreloadedQuery, queryClient } from '#lib/queries/client.ts';
  import { getPublicConfigQuery } from '#lib/queries/config-public.query.ts';
  import { getMapMarkersQuery } from '#lib/queries/map.query.ts';
  import { QueryKeys } from '#lib/queries/query-keys.ts';
  import { mapSettings } from '#lib/stores/preferences.store.ts';
  import { getAssetMediaUrl, handlePromiseError } from '#lib/utils.ts';
  import { gcj2wgs, wgs2gcj } from '#lib/utils/geo-cn.ts';
  import type { MapMarkerResponseDto } from '@immich/sdk';
  import { Alert, Container, Icon, Text, Theme, modalManager, themeManager } from '@immich/ui';
  import { mdiCog, mdiImageMultiple, mdiMap, mdiMapMarker } from '@mdi/js';
  import type { Feature, GeoJsonProperties, Geometry, Point } from 'geojson';
  import { isEqual, omit } from 'lodash-es';
  import { DateTime, Duration } from 'luxon';
  import {
    GlobeControl,
    LngLat,
    LngLatBounds,
    Marker,
    type GeoJSONSource,
    type LngLatLike,
    type Map,
    type MapMouseEvent,
  } from 'maplibre-gl';
  import { onDestroy, onMount, tick, untrack } from 'svelte';
  import { t } from 'svelte-i18n';
  import {
    AttributionControl,
    Control,
    ControlButton,
    ControlGroup,
    GeoJSON,
    GeolocateControl,
    MapLibre,
    MarkerLayer,
    NavigationControl,
    Popup,
    ScaleControl,
  } from 'svelte-maplibre';
  import { afterNavigate } from '$app/navigation';
  import type { SelectionBBox } from './types';

  const query = createPreloadedQuery(getPublicConfigQuery);
  const publicConfig = $derived(query.data);

  interface Props {
    mapMarkers?: MapMarkerResponseDto[];
    showSettings?: boolean;
    zoom?: number | undefined;
    center?: LngLatLike | undefined;
    hash?: boolean;
    simplified?: boolean;
    clickable?: boolean;
    useLocationPin?: boolean;
    onOpenInMapView?: (() => Promise<void> | void) | undefined;
    onSelect?: (assetIds: string[]) => void;
    onClusterSelect?: (assetIds: string[], bbox: SelectionBBox) => void;
    onViewportClose?: () => void;
    viewportGridActive?: boolean;
    autoOpenPanel?: boolean;
    onClickPoint?: ({ lat, lng }: { lat: number; lng: number }) => void;
    popup?: import('svelte').Snippet<[{ marker: MapMarkerResponseDto }]>;
    rounded?: boolean;
    showSimpleControls?: boolean;
    autoFitBounds?: boolean;
  }

  let {
    mapMarkers = $bindable(),
    showSettings = true,
    zoom = undefined,
    center = $bindable(undefined),
    hash = false,
    simplified = false,
    clickable = false,
    useLocationPin = false,
    onOpenInMapView = undefined,
    onSelect = () => {},
    onClusterSelect,
    onViewportClose,
    viewportGridActive = false,
    autoOpenPanel = false,
    onClickPoint = () => {},
    popup,
    rounded = false,
    showSimpleControls = true,
    autoFitBounds = true,
  }: Props = $props();

  // Dragging the map continuously fires viewport selections. Debounce those, but let a
  // cluster click take effect immediately and cancel any pending viewport selection,
  // otherwise both write to the timeline and the panel ends up with two sets of photos.
  let selectTimer: ReturnType<typeof setTimeout> | undefined;
  let lastClusterSelectAt = 0;

  const selectNow = (ids: string[], bbox: SelectionBBox) => {
    clearTimeout(selectTimer);
    selectTimer = undefined;
    lastClusterSelectAt = Date.now();
    onClusterSelect?.(ids, bbox);
  };

  const selectLazy = (ids: string[], bbox: SelectionBBox) => {
    clearTimeout(selectTimer);
    selectTimer = setTimeout(() => {
      selectTimer = undefined;
      onClusterSelect?.(ids, bbox);
    }, 180);
  };

  // Calculate initial bounds from markers once during initialization
  const initialBounds = (() => {
    if (!autoFitBounds || center || zoom !== undefined || !mapMarkers || mapMarkers.length === 0) {
      return undefined;
    }

    const bounds = new LngLatBounds();
    for (const marker of mapMarkers) {
      bounds.extend(wgs2gcj(marker.lon, marker.lat));
    }
    return bounds;
  })();

  let map: Map | undefined = $state();
  let marker: Marker | null = null;

  const mapTheme = $derived($mapSettings.allowDarkMode ? themeManager.value : Theme.Light);
  const styleUrl = $derived(mapTheme === Theme.Dark ? publicConfig.map.darkStyle : publicConfig.map.lightStyle);

  export function addClipMapMarker(lng: number, lat: number) {
    if (!map) {
      return;
    }

    if (marker) {
      marker.remove();
    }

    const [mapLng, mapLat] = wgs2gcj(lng, lat);
    center = { lng: mapLng, lat: mapLat };
    marker = new Marker().setLngLat([mapLng, mapLat]).addTo(map);
  }

  function handleAssetClick(assetId: string, map: Map | null) {
    if (!map) {
      return;
    }
    onSelect([assetId]);
  }

  async function handleClusterClick(clusterId: number, map: Map | null) {
    if (!map) {
      return;
    }

    const mapSource = map.getSource('geojson') as GeoJSONSource;
    const leaves = await mapSource.getClusterLeaves(clusterId, 1_000_000, 0);
    const ids = leaves.map((leaf) => leaf.properties?.id as string);

    if (onClusterSelect && ids.length > 1) {
      const [firstLongitude, firstLatitude] = (leaves[0].geometry as Point).coordinates;
      let west = firstLongitude;
      let south = firstLatitude;
      let east = firstLongitude;
      let north = firstLatitude;

      for (const leaf of leaves.slice(1)) {
        const [longitude, latitude] = (leaf.geometry as Point).coordinates;
        west = Math.min(west, longitude);
        south = Math.min(south, latitude);
        east = Math.max(east, longitude);
        north = Math.max(north, latitude);
      }

      // Feature coordinates are in GCJ-02; the timeline API queries WGS-84 assets.
      const [westWgs, southWgs] = gcj2wgs(west, south);
      const [eastWgs, northWgs] = gcj2wgs(east, north);
      const bbox = { west: westWgs, south: southWgs, east: eastWgs, north: northWgs };
      selectNow(ids, bbox);
      return;
    }

    clearTimeout(selectTimer);
    selectTimer = undefined;
    onSelect(ids);
  }

  function handleMapClick(event: MapMouseEvent) {
    if (!clickable) {
      return;
    }

    const { lng, lat } = event.lngLat;
    const [wgsLng, wgsLat] = gcj2wgs(lng, lat);
    onClickPoint({ lng: wgsLng, lat: wgsLat });

    if (marker) {
      marker.remove();
    }

    if (map) {
      marker = new Marker().setLngLat([lng, lat]).addTo(map);
    }
  }

  type FeaturePoint = Feature<Point, { id: string; city: string | null; state: string | null; country: string | null }>;

  const asFeature = (marker: MapMarkerResponseDto): FeaturePoint => {
    return {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: wgs2gcj(marker.lon, marker.lat) },
      properties: {
        id: marker.id,
        city: marker.city,
        state: marker.state,
        country: marker.country,
      },
    };
  };

  const asMarker = (feature: Feature<Geometry, GeoJsonProperties>): MapMarkerResponseDto => {
    const featurePoint = feature as FeaturePoint;
    const coords = LngLat.convert(featurePoint.geometry.coordinates as [number, number]);
    const [lon, lat] = gcj2wgs(coords.lng, coords.lat);
    return {
      lat,
      lon,
      id: featurePoint.properties.id,
      city: featurePoint.properties.city,
      state: featurePoint.properties.state,
      country: featurePoint.properties.country,
    };
  };

  function getFileCreatedDates() {
    const { relativeDate, dateAfter, dateBefore } = $mapSettings;

    if (relativeDate) {
      const duration = Duration.fromISO(relativeDate);
      return {
        fileCreatedAfter: duration.isValid ? DateTime.now().minus(duration).toUTC().toISO() : undefined,
      };
    }

    return {
      // $mapSettings stores no value as an empty string
      fileCreatedAfter: dateAfter || undefined,
      fileCreatedBefore: dateBefore || undefined,
    };
  }

  async function loadMapMarkers() {
    await queryClient.cancelQueries({ queryKey: QueryKeys.mapMarkers() });

    const { includeArchived, onlyFavorites, withPartners, withSharedAlbums } = $mapSettings;
    const { fileCreatedAfter, fileCreatedBefore } = getFileCreatedDates();

    return queryClient.query(
      getMapMarkersQuery({
        isArchived: includeArchived || undefined,
        isFavorite: onlyFavorites || undefined,
        fileCreatedAfter,
        fileCreatedBefore,
        withPartners: withPartners || undefined,
        withSharedAlbums: withSharedAlbums || undefined,
      }),
    );
  }

  const handleSettingsClick = async () => {
    const settings = await modalManager.show(MapSettingsModal);
    if (settings) {
      const shouldUpdate = !isEqual(omit(settings, 'allowDarkMode'), omit($mapSettings, 'allowDarkMode'));
      $mapSettings = settings;

      if (shouldUpdate) {
        mapMarkers = await loadMapMarkers();
      }
    }
  };

  afterNavigate(({ shallow, type }) => {
    if (shallow && type === 'goto') return;

    if (!map) {
      return;
    }

    map.resize();

    if (location.hash) {
      const hashChangeEvent = new HashChangeEvent('hashchange');
      // eslint-disable-next-line unicorn/no-unnecessary-global-this
      globalThis.dispatchEvent(hashChangeEvent);
    }
  });

  onMount(async () => {
    if (!mapMarkers) {
      mapMarkers = await loadMapMarkers();
    }
    if (autoOpenPanel) {
      // Wait for the map to finish rendering before opening the panel
      await tick();
      if (map) {
        map.resize();
        await map.once('idle');
        handleViewportSelect();
      }
    }
  });

  onDestroy(() => {
    clearTimeout(selectTimer);
    void queryClient.cancelQueries({ queryKey: QueryKeys.mapMarkers() });
  });

  $effect(() => {
    map?.setStyle(styleUrl, {
      transformStyle: (previousStyle, nextStyle) => {
        if (previousStyle) {
          // Preserves the custom map markers from the previous style when the theme is switched
          // Required until https://github.com/dimfeld/svelte-maplibre/issues/146 is fixed
          const customLayers = previousStyle.layers.filter((l) => l.type === 'fill' && l.source === 'geojson');
          const layers = nextStyle.layers.concat(customLayers);
          const sources = nextStyle.sources;

          for (const [key, value] of Object.entries(previousStyle.sources || {})) {
            if (key.startsWith('geojson')) {
              sources[key] = value;
            }
          }

          return {
            ...nextStyle,
            sources,
            layers,
          };
        }
        return nextStyle;
      },
    });
  });

  $effect(() => {
    if (!center || !zoom) {
      return;
    }

    untrack(() => map?.jumpTo({ center, zoom }));
  });

  const handleViewportSelect = () => {
    if (!map || !onClusterSelect || !mapMarkers) {
      return;
    }
    const bounds = map.getBounds();
    const west = bounds.getWest();
    const east = bounds.getEast();

    // When zoomed out enough to see the whole world, show all markers
    const showAll = east - west >= 360;
    const visibleIds = showAll
      ? mapMarkers.map(({ id }) => id)
      : mapMarkers
          .filter(({ lon, lat }) => {
            const [mapLng, mapLat] = wgs2gcj(lon, lat);
            return bounds.contains([mapLng, mapLat]);
          })
          .map(({ id }) => id);

    const [westWgs, southWgs] = showAll ? [-180, -90] : gcj2wgs(west, bounds.getSouth());
    const [eastWgs, northWgs] = showAll ? [180, 90] : gcj2wgs(east, bounds.getNorth());
    const bbox: SelectionBBox = {
      west: westWgs,
      south: southWgs,
      east: eastWgs,
      north: northWgs,
    };
    selectLazy(visibleIds, bbox);
  };

  const handleMoveEnd = () => {
    // Opening the panel resizes the map and fires moveend; do not let that overwrite
    // the cluster the user just selected.
    if (Date.now() - lastClusterSelectAt < 1200) {
      return;
    }
    if (viewportGridActive && !assetViewerManager.isViewing) {
      handleViewportSelect();
    }
  };

  const onAssetsChanged = async () => {
    mapMarkers = await loadMapMarkers();
  };
</script>

<OnEvents onAssetsDelete={onAssetsChanged} onAssetsArchive={onAssetsChanged} onAssetsUnarchive={onAssetsChanged} />
<svelte:boundary>
  <!--  We handle style loading ourselves so we set style blank here -->
  <MapLibre
    {hash}
    style=""
    class="h-full {rounded ? 'rounded-2xl' : 'rounded-none'}"
    {zoom}
    {center}
    bounds={initialBounds}
    fitBoundsOptions={{ padding: 50, maxZoom: 15 }}
    attributionControl={false}
    diffStyleUpdates={true}
    onload={(event: Map) => {
      event.setMaxZoom(18);
      event.on('click', handleMapClick);
      event.on('moveend', handleMoveEnd);
      if (!simplified) {
        event.addControl(new GlobeControl(), 'top-left');
      }
      if (!simplified) {
        event.addControl(createAmapLayerControl(), 'top-right');
      }
    }}
    bind:map
  >
    {#snippet children({ map }: { map: Map })}
      {#if showSimpleControls}
        <NavigationControl position="top-left" showCompass={!simplified} />

        {#if !simplified}
          <GeolocateControl position="top-left" />
          {#if onClusterSelect}
            <Control position="top-left">
              <ControlGroup>
                <ControlButton onclick={() => (viewportGridActive ? onViewportClose?.() : handleViewportSelect())}>
                  <Icon title={$t('show_photos_in_area')} icon={mdiImageMultiple} size="70%" class="text-black/80" />
                </ControlButton>
              </ControlGroup>
            </Control>
          {/if}
          <ScaleControl />
          <AttributionControl compact={false} />
        {/if}
      {/if}

      {#if showSettings}
        <Control>
          <ControlGroup>
            <ControlButton onclick={handleSettingsClick}>
              <Icon icon={mdiCog} size="70%" class="text-black/80" />
            </ControlButton>
          </ControlGroup>
        </Control>
      {/if}

      {#if onOpenInMapView && showSimpleControls}
        <Control position="top-right">
          <ControlGroup>
            <ControlButton onclick={() => onOpenInMapView()}>
              <Icon title={$t('open_in_map_view')} icon={mdiMap} size="100%" class="text-black/80" />
            </ControlButton>
          </ControlGroup>
        </Control>
      {/if}

      <GeoJSON
        data={{
          type: 'FeatureCollection',
          features: mapMarkers?.map((marker) => asFeature(marker)) ?? [],
        }}
        id="geojson"
        cluster={{ radius: 80, maxZoom: 20 }}
      >
        <MarkerLayer
          applyToClusters
          asButton
          onclick={(event) => handlePromiseError(handleClusterClick(event.feature.properties?.cluster_id, map))}
        >
          {#snippet children({ feature })}
            <div
              class="flex size-10 items-center justify-center rounded-full bg-immich-primary font-mono font-bold text-white opacity-90 shadow-lg transition-all duration-200 hover:bg-immich-dark-primary hover:text-immich-dark-bg"
            >
              {feature.properties?.point_count?.toLocaleString()}
            </div>
          {/snippet}
        </MarkerLayer>
        <MarkerLayer
          applyToClusters={false}
          asButton
          onclick={(event) => {
            if (!popup) {
              handleAssetClick(event.feature.properties?.id, map);
            }
          }}
        >
          {#snippet children({ feature }: { feature: Feature })}
            {#if useLocationPin}
              <Icon icon={mdiMapMarker} size="50px" class="translate-y-[calc(5px-50%)] text-primary" />
            {:else}
              <img
                src={getAssetMediaUrl({ id: feature.properties?.id })}
                class="size-15 rounded-full border-2 border-immich-primary bg-immich-primary object-cover shadow-lg transition-all duration-200 hover:scale-150 hover:border-immich-dark-primary"
                alt={feature.properties?.city && feature.properties.country
                  ? $t('map_marker_for_image', {
                      values: { city: feature.properties.city, country: feature.properties.country },
                    })
                  : $t('map_marker_with_image')}
              />
            {/if}
            {#if popup}
              <Popup offset={[0, -30]} openOn="click" closeOnClickOutside>
                {@render popup({ marker: asMarker(feature) })}
              </Popup>
            {/if}
          {/snippet}
        </MarkerLayer>
      </GeoJSON>
    {/snippet}
  </MapLibre>

  {#snippet failed()}
    <Container size="small" class="p-2">
      <Alert color="warning" title={$t('errors.unable_to_load_map')} size={simplified ? 'medium' : 'large'}>
        <Text size={simplified ? 'small' : 'medium'}>{$t('errors.unable_to_load_map_description')}</Text>
      </Alert>
    </Container>
  {/snippet}
</svelte:boundary>
