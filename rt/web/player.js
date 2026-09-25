const currentAudio = () => element.querySelector('audio');
const recentErrors = new Map();
const report = (kind, error) => {
  const message = String(error?.stack || error?.message || error).slice(0, 1200);
  const key = `${kind}:${message}`;
  if (Date.now() - (recentErrors.get(key) || 0) < 5000) return;
  recentErrors.set(key, Date.now());
  trigger('client_log', { kind, message });
};
window.addEventListener('error', event => report('browser.error', event.error || event.message));
window.addEventListener('unhandledrejection', event => report('browser.promise', event.reason));

const formatTime = seconds => {
  if (!Number.isFinite(seconds)) return '0:00';
  const whole = Math.floor(seconds);
  const parts = [Math.floor(whole / 3600), Math.floor(whole / 60) % 60, whole % 60];
  return parts[0] ? `${parts[0]}:${String(parts[1]).padStart(2, '0')}:${String(parts[2]).padStart(2, '0')}`
    : `${parts[1]}:${String(parts[2]).padStart(2, '0')}`;
};

const seekTo = seconds => {
  const audio = currentAudio();
  if (!audio || !Number.isFinite(seconds)) return;
  const start = () => {
    audio.currentTime = Math.max(0, Math.min(seconds, audio.duration || seconds));
    audio.play().catch(error => report('audio.play', error));
  };
  if (audio.readyState >= HTMLMediaElement.HAVE_METADATA) start();
  else audio.addEventListener('loadedmetadata', start, { once: true });
};

const chapters = () => {
  const headings = [...document.querySelectorAll('#rt-preview .rt-document h3')];
  const starts = headings.map(heading => {
    let sibling = heading.nextElementSibling;
    while (sibling && !/^H[23]$/.test(sibling.tagName)) {
      const timecode = sibling.querySelector('button.rt-timecode');
      if (timecode) return Number(timecode.dataset.seconds);
      sibling = sibling.nextElementSibling;
    }
    return null;
  }).filter(Number.isFinite);
  return [...new Set(starts)].sort((a, b) => a - b);
};

const waveformCache = new Map();
const drawWaveform = (canvas, audio, peaks) => {
  if (!canvas.isConnected) return;
  const width = Math.max(1, canvas.clientWidth);
  const height = canvas.clientHeight || 76;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const ctx = canvas.getContext('2d');
  ctx.scale(ratio, ratio);
  const data = peaks?.length ? peaks : Array.from({ length: 160 }, (_, i) => 8 + 7 * Math.abs(Math.sin(i * 1.7)));
  const played = Number.isFinite(audio.duration) && audio.duration > 0 ? audio.currentTime / audio.duration : 0;
  const spacing = width / data.length;
  const barWidth = Math.max(1, Math.min(3, spacing * 0.55));
  data.forEach((value, i) => {
    const barHeight = Math.max(3, value * (height - 7) / 76);
    ctx.fillStyle = i / data.length <= played ? '#e98a16' : '#8996aa';
    ctx.fillRect(i * spacing, (height - barHeight) / 2, barWidth, barHeight);
  });
  if (played > 0 && played < 1) {
    ctx.fillStyle = '#d6c7ed';
    ctx.fillRect(played * width, 0, 2, height);
  }
};

const loadPeaks = async (canvas, audio, attempt = 0) => {
  if (!canvas.isConnected) return;
  const url = canvas.dataset.peaksUrl;
  if (waveformCache.has(url)) {
    drawWaveform(canvas, audio, waveformCache.get(url));
    return;
  }
  try {
    const response = await fetch(url, { cache: 'no-store' });
    if (response.status === 202 && attempt < 70) {
      setTimeout(() => loadPeaks(canvas, audio, attempt + 1), 1000);
      return;
    }
    if (!response.ok) throw new Error(`Forma d'onda HTTP ${response.status}`);
    const peaks = (await response.json()).peaks;
    waveformCache.set(url, peaks || []);
    drawWaveform(canvas, audio, peaks);
  } catch (error) {
    report('audio.waveform', error);
  }
};

const initPlayer = () => {
  const audio = currentAudio();
  const canvas = element.querySelector('canvas.rt-waveform');
  if (!audio || !canvas || audio.dataset.rtObserved) return;
  audio.dataset.rtObserved = 'true';
  const current = element.querySelector('[data-audio-current]');
  const duration = element.querySelector('[data-audio-duration]');
  const play = element.querySelector('[data-audio-action="play"]');
  let recoveryCount = 0;
  let recoveryAt = 0;
  let recoveryTimer;
  const redraw = () => drawWaveform(canvas, audio, waveformCache.get(canvas.dataset.peaksUrl));
  const sync = () => {
    current.textContent = formatTime(audio.currentTime);
    duration.textContent = formatTime(audio.duration);
    play.textContent = audio.paused ? '▶' : '❚❚';
    play.setAttribute('aria-label', audio.paused ? 'Riproduci' : 'Pausa');
    redraw();
  };
  const recover = kind => {
    report(`audio.${kind}`, `Riproduzione ferma a ${audio.currentTime.toFixed(1)} s`);
    if (audio.paused || recoveryTimer) return;
    const stoppedAt = audio.currentTime;
    recoveryTimer = setTimeout(() => {
      recoveryTimer = null;
      if (!audio.isConnected || audio.paused || audio.currentTime > stoppedAt + 0.4) return;
      if (Date.now() - recoveryAt > 60000) recoveryCount = 0;
      if (recoveryCount >= 2) return;
      recoveryCount += 1;
      recoveryAt = Date.now();
      report('audio.recover', `Nuovo tentativo dal secondo ${stoppedAt.toFixed(1)}`);
      audio.load();
      audio.addEventListener('loadedmetadata', () => {
        audio.currentTime = stoppedAt;
        audio.play().catch(error => report('audio.recover.play', error));
      }, { once: true });
    }, 3500);
  };
  audio.addEventListener('error', () => report('audio.error', audio.error?.message || 'File audio non riproducibile'));
  audio.addEventListener('stalled', () => recover('stalled'));
  audio.addEventListener('waiting', () => recover('waiting'));
  for (const event of ['loadedmetadata', 'timeupdate', 'durationchange', 'play', 'pause', 'ended']) {
    audio.addEventListener(event, sync);
  }
  canvas.addEventListener('click', event => {
    if (!Number.isFinite(audio.duration)) return;
    seekTo((event.clientX - canvas.getBoundingClientRect().left) / canvas.clientWidth * audio.duration);
  });
  new ResizeObserver(redraw).observe(canvas);
  loadPeaks(canvas, audio);
  sync();
};

element.addEventListener('click', event => {
  const button = event.target.closest('[data-audio-action]');
  if (!button) return;
  const audio = currentAudio();
  if (!audio) return;
  if (button.dataset.audioAction === 'play') {
    if (audio.paused) audio.play().catch(error => report('audio.play', error));
    else audio.pause();
  } else if (button.dataset.audioAction === 'mute') {
    audio.muted = !audio.muted;
    button.textContent = audio.muted ? '◖×' : '◖))';
  } else if (button.dataset.audioAction === 'speed') {
    const speeds = [1, 1.25, 1.5, 2];
    audio.playbackRate = speeds[(speeds.indexOf(audio.playbackRate) + 1) % speeds.length];
    button.textContent = `${audio.playbackRate}×`;
  }
});
document.addEventListener('click', event => {
  const timecode = event.target.closest('#rt-preview button.rt-timecode');
  if (timecode) {
    seekTo(Number(timecode.dataset.seconds));
    return;
  }
  const button = event.target.closest('#rt-lesson-audio button[data-chapter]');
  if (!button) return;
  const audio = currentAudio();
  if (!audio) return;
  const positions = chapters();
  const now = audio.currentTime;
  const target = button.dataset.chapter === 'next'
    ? positions.find(seconds => seconds > now + 1)
    : positions[positions.findLastIndex(seconds => seconds <= now + .5) - 1];
  if (target !== undefined) seekTo(target);
});
initPlayer();
watch('value', () => requestAnimationFrame(initPlayer));
