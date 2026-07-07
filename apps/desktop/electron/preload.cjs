const { contextBridge, ipcRenderer, webUtils } = require('electron')

contextBridge.exposeInMainWorld('zebDesktop', {
  getConnection: profile => ipcRenderer.invoke('zeb:connection', profile),
  revalidateConnection: () => ipcRenderer.invoke('zeb:connection:revalidate'),
  touchBackend: profile => ipcRenderer.invoke('zeb:backend:touch', profile),
  getGatewayWsUrl: profile => ipcRenderer.invoke('zeb:gateway:ws-url', profile),
  openSessionWindow: (sessionId, opts) => ipcRenderer.invoke('zeb:window:openSession', sessionId, opts),
  openNewSessionWindow: () => ipcRenderer.invoke('zeb:window:openNewSession'),
  petOverlay: {
    // Main renderer → main process: window lifecycle + drag. `request` is
    // `{ bounds, screen }`; resolves with the screen bounds it actually used.
    open: request => ipcRenderer.invoke('zeb:pet-overlay:open', request),
    close: () => ipcRenderer.invoke('zeb:pet-overlay:close'),
    setBounds: bounds => ipcRenderer.send('zeb:pet-overlay:set-bounds', bounds),
    setIgnoreMouse: ignore => ipcRenderer.send('zeb:pet-overlay:ignore-mouse', ignore),
    // Flip the overlay focusable (and focus it) while the composer needs keys.
    setFocusable: focusable => ipcRenderer.send('zeb:pet-overlay:set-focusable', focusable),
    // Main renderer → overlay (forwarded by main): push the latest pet state.
    pushState: payload => ipcRenderer.send('zeb:pet-overlay:state', payload),
    // Overlay → main renderer (forwarded by main): pop back in / composer submit.
    control: payload => ipcRenderer.send('zeb:pet-overlay:control', payload),
    // Overlay subscribes to state pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('zeb:pet-overlay:state', listener)
      return () => ipcRenderer.removeListener('zeb:pet-overlay:state', listener)
    },
    // Main renderer subscribes to overlay control messages.
    onControl: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('zeb:pet-overlay:control', listener)
      return () => ipcRenderer.removeListener('zeb:pet-overlay:control', listener)
    }
  },
  getBootProgress: () => ipcRenderer.invoke('zeb:boot-progress:get'),
  getConnectionConfig: profile => ipcRenderer.invoke('zeb:connection-config:get', profile),
  saveConnectionConfig: payload => ipcRenderer.invoke('zeb:connection-config:save', payload),
  applyConnectionConfig: payload => ipcRenderer.invoke('zeb:connection-config:apply', payload),
  testConnectionConfig: payload => ipcRenderer.invoke('zeb:connection-config:test', payload),
  probeConnectionConfig: remoteUrl => ipcRenderer.invoke('zeb:connection-config:probe', remoteUrl),
  oauthLoginConnectionConfig: remoteUrl => ipcRenderer.invoke('zeb:connection-config:oauth-login', remoteUrl),
  oauthLogoutConnectionConfig: remoteUrl => ipcRenderer.invoke('zeb:connection-config:oauth-logout', remoteUrl),
  profile: {
    get: () => ipcRenderer.invoke('zeb:profile:get'),
    set: name => ipcRenderer.invoke('zeb:profile:set', name)
  },
  api: request => ipcRenderer.invoke('zeb:api', request),
  notify: payload => ipcRenderer.invoke('zeb:notify', payload),
  requestMicrophoneAccess: () => ipcRenderer.invoke('zeb:requestMicrophoneAccess'),
  readFileDataUrl: filePath => ipcRenderer.invoke('zeb:readFileDataUrl', filePath),
  readFileText: filePath => ipcRenderer.invoke('zeb:readFileText', filePath),
  selectPaths: options => ipcRenderer.invoke('zeb:selectPaths', options),
  writeClipboard: text => ipcRenderer.invoke('zeb:writeClipboard', text),
  saveImageFromUrl: url => ipcRenderer.invoke('zeb:saveImageFromUrl', url),
  saveImageBuffer: (data, ext) => ipcRenderer.invoke('zeb:saveImageBuffer', { data, ext }),
  saveClipboardImage: () => ipcRenderer.invoke('zeb:saveClipboardImage'),
  getPathForFile: file => {
    try {
      return webUtils.getPathForFile(file) || ''
    } catch {
      return ''
    }
  },
  normalizePreviewTarget: (target, baseDir) => ipcRenderer.invoke('zeb:normalizePreviewTarget', target, baseDir),
  watchPreviewFile: url => ipcRenderer.invoke('zeb:watchPreviewFile', url),
  stopPreviewFileWatch: id => ipcRenderer.invoke('zeb:stopPreviewFileWatch', id),
  setTitleBarTheme: payload => ipcRenderer.send('zeb:titlebar-theme', payload),
  setNativeTheme: mode => ipcRenderer.send('zeb:native-theme', mode),
  setTranslucency: payload => ipcRenderer.send('zeb:translucency', payload),
  setPreviewShortcutActive: active => ipcRenderer.send('zeb:previewShortcutActive', Boolean(active)),
  openExternal: url => ipcRenderer.invoke('zeb:openExternal', url),
  openPreviewInBrowser: url => ipcRenderer.invoke('zeb:openPreviewInBrowser', url),
  fetchLinkTitle: url => ipcRenderer.invoke('zeb:fetchLinkTitle', url),
  sanitizeWorkspaceCwd: cwd => ipcRenderer.invoke('zeb:workspace:sanitize', cwd),
  settings: {
    getDefaultProjectDir: () => ipcRenderer.invoke('zeb:setting:defaultProjectDir:get'),
    setDefaultProjectDir: dir => ipcRenderer.invoke('zeb:setting:defaultProjectDir:set', dir),
    pickDefaultProjectDir: () => ipcRenderer.invoke('zeb:setting:defaultProjectDir:pick')
  },
  zoom: {
    // Current zoom of this window, as { level, percent }.
    get: () => ipcRenderer.invoke('zeb:zoom:get'),
    setPercent: percent => ipcRenderer.send('zeb:zoom:set-percent', percent),
    // Fires on every zoom change, including the Ctrl/Cmd +/-/0 shortcuts,
    // so the settings UI can stay in sync with the keyboard.
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('zeb:zoom:changed', listener)
      return () => ipcRenderer.removeListener('zeb:zoom:changed', listener)
    }
  },
  revealLogs: () => ipcRenderer.invoke('zeb:logs:reveal'),
  getRecentLogs: () => ipcRenderer.invoke('zeb:logs:recent'),
  readDir: dirPath => ipcRenderer.invoke('zeb:fs:readDir', dirPath),
  gitRoot: startPath => ipcRenderer.invoke('zeb:fs:gitRoot', startPath),
  revealPath: targetPath => ipcRenderer.invoke('zeb:fs:reveal', targetPath),
  renamePath: (targetPath, newName) => ipcRenderer.invoke('zeb:fs:rename', targetPath, newName),
  writeTextFile: (filePath, content) => ipcRenderer.invoke('zeb:fs:writeText', filePath, content),
  trashPath: targetPath => ipcRenderer.invoke('zeb:fs:trash', targetPath),
  git: {
    worktreeList: repoPath => ipcRenderer.invoke('zeb:git:worktreeList', repoPath),
    worktreeAdd: (repoPath, options) => ipcRenderer.invoke('zeb:git:worktreeAdd', repoPath, options),
    worktreeRemove: (repoPath, worktreePath, options) =>
      ipcRenderer.invoke('zeb:git:worktreeRemove', repoPath, worktreePath, options),
    branchSwitch: (repoPath, branch) => ipcRenderer.invoke('zeb:git:branchSwitch', repoPath, branch),
    branchList: repoPath => ipcRenderer.invoke('zeb:git:branchList', repoPath),
    repoStatus: repoPath => ipcRenderer.invoke('zeb:git:repoStatus', repoPath),
    fileDiff: (repoPath, filePath) => ipcRenderer.invoke('zeb:git:fileDiff', repoPath, filePath),
    scanRepos: (roots, options) => ipcRenderer.invoke('zeb:git:scanRepos', roots, options),
    review: {
      list: (repoPath, scope, baseRef) => ipcRenderer.invoke('zeb:git:review:list', repoPath, scope, baseRef),
      diff: (repoPath, filePath, scope, baseRef, staged) =>
        ipcRenderer.invoke('zeb:git:review:diff', repoPath, filePath, scope, baseRef, staged),
      stage: (repoPath, filePath) => ipcRenderer.invoke('zeb:git:review:stage', repoPath, filePath),
      unstage: (repoPath, filePath) => ipcRenderer.invoke('zeb:git:review:unstage', repoPath, filePath),
      revert: (repoPath, filePath) => ipcRenderer.invoke('zeb:git:review:revert', repoPath, filePath),
      revParse: (repoPath, ref) => ipcRenderer.invoke('zeb:git:review:revParse', repoPath, ref),
      commit: (repoPath, message, push) => ipcRenderer.invoke('zeb:git:review:commit', repoPath, message, push),
      commitContext: repoPath => ipcRenderer.invoke('zeb:git:review:commitContext', repoPath),
      push: repoPath => ipcRenderer.invoke('zeb:git:review:push', repoPath),
      shipInfo: repoPath => ipcRenderer.invoke('zeb:git:review:shipInfo', repoPath),
      createPr: repoPath => ipcRenderer.invoke('zeb:git:review:createPr', repoPath)
    }
  },
  terminal: {
    dispose: id => ipcRenderer.invoke('zeb:terminal:dispose', id),
    resize: (id, size) => ipcRenderer.invoke('zeb:terminal:resize', id, size),
    start: options => ipcRenderer.invoke('zeb:terminal:start', options),
    write: (id, data) => ipcRenderer.invoke('zeb:terminal:write', id, data),
    onData: (id, callback) => {
      const channel = `zeb:terminal:${id}:data`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)
      return () => ipcRenderer.removeListener(channel, listener)
    },
    onExit: (id, callback) => {
      const channel = `zeb:terminal:${id}:exit`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)
      return () => ipcRenderer.removeListener(channel, listener)
    }
  },
  onClosePreviewRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('zeb:close-preview-requested', listener)
    return () => ipcRenderer.removeListener('zeb:close-preview-requested', listener)
  },
  onOpenUpdatesRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('zeb:open-updates', listener)
    return () => ipcRenderer.removeListener('zeb:open-updates', listener)
  },
  onDeepLink: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeb:deep-link', listener)
    return () => ipcRenderer.removeListener('zeb:deep-link', listener)
  },
  signalDeepLinkReady: () => ipcRenderer.invoke('zeb:deep-link-ready'),
  onWindowStateChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeb:window-state-changed', listener)
    return () => ipcRenderer.removeListener('zeb:window-state-changed', listener)
  },
  onFocusSession: callback => {
    const listener = (_event, sessionId) => callback(sessionId)
    ipcRenderer.on('zeb:focus-session', listener)
    return () => ipcRenderer.removeListener('zeb:focus-session', listener)
  },
  onNotificationAction: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeb:notification-action', listener)
    return () => ipcRenderer.removeListener('zeb:notification-action', listener)
  },
  onPreviewFileChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeb:preview-file-changed', listener)
    return () => ipcRenderer.removeListener('zeb:preview-file-changed', listener)
  },
  onBackendExit: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeb:backend-exit', listener)
    return () => ipcRenderer.removeListener('zeb:backend-exit', listener)
  },
  onPowerResume: callback => {
    const listener = () => callback()
    ipcRenderer.on('zeb:power-resume', listener)
    return () => ipcRenderer.removeListener('zeb:power-resume', listener)
  },
  onBootProgress: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeb:boot-progress', listener)
    return () => ipcRenderer.removeListener('zeb:boot-progress', listener)
  },
  // First-launch bootstrap progress -- emitted by the install.ps1 stage
  // runner in main.cjs (apps/desktop/electron/bootstrap-runner.cjs).
  // Renderer's install overlay subscribes to live events and queries the
  // current snapshot via getBootstrapState() to recover after a devtools
  // reload mid-bootstrap.
  getBootstrapState: () => ipcRenderer.invoke('zeb:bootstrap:get'),
  resetBootstrap: () => ipcRenderer.invoke('zeb:bootstrap:reset'),
  repairBootstrap: () => ipcRenderer.invoke('zeb:bootstrap:repair'),
  cancelBootstrap: () => ipcRenderer.invoke('zeb:bootstrap:cancel'),
  onBootstrapEvent: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('zeb:bootstrap:event', listener)
    return () => ipcRenderer.removeListener('zeb:bootstrap:event', listener)
  },
  getVersion: () => ipcRenderer.invoke('zeb:version'),
  getRemoteDisplayReason: () => ipcRenderer.invoke('zeb:get-remote-display-reason'),
  uninstall: {
    summary: () => ipcRenderer.invoke('zeb:uninstall:summary'),
    run: mode => ipcRenderer.invoke('zeb:uninstall:run', { mode })
  },
  updates: {
    check: () => ipcRenderer.invoke('zeb:updates:check'),
    apply: opts => ipcRenderer.invoke('zeb:updates:apply', opts),
    getBranch: () => ipcRenderer.invoke('zeb:updates:branch:get'),
    setBranch: name => ipcRenderer.invoke('zeb:updates:branch:set', name),
    onProgress: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('zeb:updates:progress', listener)
      return () => ipcRenderer.removeListener('zeb:updates:progress', listener)
    }
  },
  themes: {
    fetchMarketplace: id => ipcRenderer.invoke('zeb:vscode-theme:fetch', id),
    searchMarketplace: query => ipcRenderer.invoke('zeb:vscode-theme:search', query)
  }
})
