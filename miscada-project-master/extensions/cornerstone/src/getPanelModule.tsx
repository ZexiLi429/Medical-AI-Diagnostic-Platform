import React from 'react';

import { Toolbox } from '@ohif/extension-default';
import PanelSegmentation from './panels/PanelSegmentation';
import ActiveViewportWindowLevel from './components/ActiveViewportWindowLevel';
import PanelMeasurement from './panels/PanelMeasurement';
import PanelUnSAM from './panels/PanelUnSAM';

const AI_BUTTON: React.CSSProperties = {
  width: '100%', padding: '7px 10px', marginBottom: 6, borderRadius: 6,
  border: '1px solid #3b82f6', background: 'linear-gradient(135deg, #1e3a5f, #1a2d4a)',
  color: '#93c5fd', fontSize: 12, fontWeight: 600, cursor: 'pointer', textAlign: 'center' as const,
};

const AIButtonsSection = ({ commandsManager }: { commandsManager: any }) => (
  <div style={{ padding: '10px 12px 6px 12px', borderBottom: '1px solid #2d3748' }}>
    <div style={{ fontSize: 11, fontWeight: 700, color: '#94a3b8', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>AI Segmentation</div>
    <button style={AI_BUTTON} onClick={() => commandsManager.runCommand('totalSegmentAll')}>Segment All Organs</button>
    <button style={{ ...AI_BUTTON, background: 'linear-gradient(135deg, #2d3748, #1a202c)', borderColor: '#4a5568', color: '#a0aec0' }} onClick={() => commandsManager.runCommand('segmentOrganByName')}>Segment Organ by Name...</button>
    <button style={{ ...AI_BUTTON, background: 'linear-gradient(135deg, #1e3a2f, #1a2d22)', borderColor: '#22c55e', color: '#86efac' }} onClick={() => commandsManager.runCommand('segmentByBBox')}>Segment by Brush/Box</button>
    <button
      style={{
        ...AI_BUTTON,
        background: 'linear-gradient(135deg, #2e1065, #1e0948)',
        borderColor: '#8b5cf6',
        color: '#c4b5fd',
        fontSize: 12,
      }}
      onClick={() => commandsManager.runCommand('generateReport')}
    >
      Generate Report
    </button>
  </div>
);

const getPanelModule = ({ commandsManager, servicesManager, extensionManager }: withAppTypes) => {
  const wrappedPanelSegmentation = ({ configuration }) => {
    return (
      <PanelSegmentation
        commandsManager={commandsManager}
        servicesManager={servicesManager}
        extensionManager={extensionManager}
        configuration={{
          ...configuration,
        }}
      />
    );
  };

  const wrappedPanelSegmentationWithAI = ({ configuration }) => {
    const { toolbarService } = servicesManager.services;

    return (
      <>
        <AIButtonsSection commandsManager={commandsManager} />
        <Toolbox
          buttonSectionId={toolbarService.sections.segmentationToolbox}
          title="Segmentation Tools"
        />
        <PanelSegmentation
          commandsManager={commandsManager}
          servicesManager={servicesManager}
          extensionManager={extensionManager}
          configuration={{
            ...configuration,
          }}
        />
      </>
    );
  };

  const wrappedPanelSegmentationNoHeader = ({ configuration }) => (
    <PanelSegmentation
      commandsManager={commandsManager}
      servicesManager={servicesManager}
      extensionManager={extensionManager}
      configuration={{ ...configuration }}
    />
  );

  const wrappedPanelSegmentationWithTools = ({ configuration }) => {
    const { toolbarService } = servicesManager.services;

    return (
      <>
        <Toolbox
          buttonSectionId={toolbarService.sections.segmentationToolbox}
          title="Segmentation Tools"
        />
        <PanelSegmentation
          commandsManager={commandsManager}
          servicesManager={servicesManager}
          extensionManager={extensionManager}
          configuration={{
            ...configuration,
          }}
        />
      </>
    );
  };

  const wrappedPanelUnSAM = ({ configuration }) => {
    return (
      <PanelUnSAM
        commandsManager={commandsManager}
        servicesManager={servicesManager}
        extensionManager={extensionManager}
        configuration={{
          ...configuration,
        }}
      />
    );
  };

  return [
    {
      name: 'activeViewportWindowLevel',
      component: () => {
        return <ActiveViewportWindowLevel servicesManager={servicesManager} />;
      },
    },
    {
      name: 'panelMeasurement',
      iconName: 'tab-linear',
      iconLabel: 'Measure',
      label: 'Measurement',
      component: PanelMeasurement,
    },
    {
      name: 'panelSegmentation',
      iconName: 'tab-segmentation',
      iconLabel: 'Segmentation',
      label: 'Segmentation',
      component: wrappedPanelSegmentation,
    },
    {
      name: 'panelSegmentationNoHeader',
      iconName: 'tab-segmentation',
      iconLabel: 'Segmentation',
      label: 'Segmentation',
      component: wrappedPanelSegmentationNoHeader,
    },
    {
      name: 'panelSegmentationWithAI',
      iconName: 'tab-segmentation',
      iconLabel: 'Seg + AI',
      label: 'Seg + AI',
      component: wrappedPanelSegmentationWithAI,
    },
    {
      name: 'panelSegmentationWithTools',
      iconName: 'tab-segmentation',
      iconLabel: 'Segmentation',
      label: 'Segmentation',
      component: wrappedPanelSegmentationWithTools,
    },
    {
      name: 'panelUnSAM',
      iconName: 'tab-unsam',
      iconLabel: 'UnSAM',
      label: 'UnSAM',
      component: wrappedPanelUnSAM,
    },
  ];
};

export default getPanelModule;
