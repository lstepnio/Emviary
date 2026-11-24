(() => {
  const buttons = document.querySelectorAll('[data-animation-toggle]');
  function stop(button) {
    const image = document.getElementById(button.dataset.animationToggle);
    if (!image) return;
    image.src = image.dataset.still;
    button.setAttribute('aria-pressed', 'false');
    button.textContent = 'Play animation';
  }
  buttons.forEach(button => {
    button.hidden = false;
    button.addEventListener('click', () => {
      const image = document.getElementById(button.dataset.animationToggle);
      if (!image) return;
      if (button.getAttribute('aria-pressed') === 'true') return stop(button);
      image.src = image.dataset.animation;
      button.setAttribute('aria-pressed', 'true');
      button.textContent = 'Pause animation';
    });
  });
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  reducedMotion.addEventListener('change', event => {
    if (event.matches) buttons.forEach(stop);
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) buttons.forEach(stop);
  });
})();
