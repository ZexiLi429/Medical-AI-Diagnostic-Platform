import { HYDRATE_SEG_SYNC_GROUP, VOI_SYNC_GROUP } from './mpr';

export const only3D = {
  id: 'only3D',
  locked: true,
  name: '3D only',
  icon: 'layout-advanced-3d-only',
  isPreset: true,
  createdDate: '2023-03-15T10:29:44.894Z',
  modifiedDate: '2023-03-15T10:29:44.894Z',
  availableTo: {},
  editableBy: {},
  protocolMatchingRules: [],
  imageLoadStrategy: 'interleaveCenter',
  displaySetSelectors: {
    activeDisplaySet: {
      seriesMatchingRules: [
        {
          weight: 1,
          attribute: 'isReconstructable',
          constraint: {
            equals: {
              value: true,
            },
          },
          required: false,  // SAM 模式下 displaySet 可能没有此属性
        },
      ],
    },
  },
  stages: [
    {
      id: 'only3DStage',
      name: 'only3D',
      viewportStructure: {
        layoutType: 'grid',
        properties: {
          rows: 1,
          columns: 1,
        },
      },
      viewports: [
        {
          viewportOptions: {
            toolGroupId: 'volume3d',
            viewportType: 'volume3d',  // 保持 volume3d 以保留彩色体渲染
            orientation: 'coronal',
            customViewportProps: {
              hideOverlays: true,
              syncGroups: [VOI_SYNC_GROUP, HYDRATE_SEG_SYNC_GROUP],
            },
          },
          displaySets: [
            {
              id: 'activeDisplaySet',
              options: {
                displayPreset: {
                  CT: 'CT-Chest-Contrast-Enhanced',
                  MR: 'MR-Default',
                  default: 'CT-Chest-Contrast-Enhanced',
                },
              },
            },
          ],
        },
      ],
    },
  ],
};
