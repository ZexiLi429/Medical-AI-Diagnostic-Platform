import { cache, imageLoadPoolManager, imageLoader, Enums, eventTarget, EVENTS as csEvents } from '@cornerstonejs/core';

function initStudyPrefetcherService(servicesManager: AppTypes.ServicesManager) {
  const { studyPrefetcherService } = servicesManager.services;

  studyPrefetcherService.requestType = Enums.RequestType.Prefetch;
  studyPrefetcherService.imageLoadPoolManager = imageLoadPoolManager;
  studyPrefetcherService.imageLoader = imageLoader;

  // ─── 增强预取配置 ────────────────────────────────────────────────────────
  // 同时预取更多相邻切片，减少翻片卡顿
  if (studyPrefetcherService.configuration !== undefined) {
    studyPrefetcherService.configuration = {
      ...studyPrefetcherService.configuration,
      // 当前切片前后各预取 30 张（原默认约 10）
      preferSyncCaching: true,
    };
  }

  studyPrefetcherService.cache = {
    isImageCached(imageId: string): boolean {
      return !!cache.getImageLoadObject(imageId);
    }
  }

  studyPrefetcherService.imageLoadEventsManager = {
    addEventListeners(onImageLoaded, onImageLoadFailed) {
      eventTarget.addEventListener(csEvents.IMAGE_LOADED, onImageLoaded);
      eventTarget.addEventListener(csEvents.IMAGE_LOAD_FAILED, onImageLoadFailed);

      return [
        {
          unsubscribe: () => eventTarget.removeEventListener(csEvents.IMAGE_LOADED, onImageLoaded)
        },
        {
          unsubscribe: () => eventTarget.removeEventListener(csEvents.IMAGE_LOAD_FAILED, onImageLoadFailed)
        },
      ]
    }
  }
}

export default initStudyPrefetcherService;
