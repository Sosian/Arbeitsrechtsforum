/* Tooltips for elements with data-toggle="tooltip": the title is shown in a
   small black box above the element while it is hovered or focused, in place
   of the browser's own title popup. Works like the Bootstrap 3 tooltip the
   site used before (same placement, same fade), without needing Bootstrap and
   jQuery for it. Without JavaScript the browser simply shows the title. */
(function () {
	var FADE_MS = 150;
	var count = 0;

	function pageOffset(node) {
		var rect = node.getBoundingClientRect();
		return { top: rect.top + window.pageYOffset, left: rect.left + window.pageXOffset };
	}

	// Move an absolutely positioned node so its box starts at the given page
	// coordinates, whatever element it is positioned relative to
	function moveTo(node, top, left, round) {
		var current = pageOffset(node);
		var style = getComputedStyle(node);
		top = top - current.top + (parseFloat(style.top) || 0);
		left = left - current.left + (parseFloat(style.left) || 0);
		node.style.top = (round ? Math.round(top) : top) + 'px';
		node.style.left = (round ? Math.round(left) : left) + 'px';
	}

	function show(el) {
		if (el._tooltip) {
			clearTimeout(el._tooltip.removeTimer);
			el._tooltip.parentNode.removeChild(el._tooltip);
		}

		var tip = document.createElement('div');
		tip.className = 'tooltip top';
		tip.setAttribute('role', 'tooltip');
		tip.id = 'tooltip' + (++count);
		tip.innerHTML = '<div class="tooltip-arrow"></div><div class="tooltip-inner"></div>';
		tip.lastChild.textContent = el.getAttribute('data-original-title');
		tip.style.top = '0';
		tip.style.left = '0';
		// Right after the element, so it is sized within the same column
		el.parentNode.insertBefore(tip, el.nextSibling);
		el.setAttribute('aria-describedby', tip.id);
		el._tooltip = tip;

		// Centred above the element
		var box = el.getBoundingClientRect();
		var pos = pageOffset(el);
		var width = tip.offsetWidth;
		var height = tip.offsetHeight;
		var top = pos.top - height + (parseInt(getComputedStyle(tip).marginTop, 10) || 0);
		var left = pos.left + box.width / 2 - width / 2;
		moveTo(tip, top, left, true);
		tip.className = 'tooltip top in';

		// Near the edge of the column the text wraps narrower once placed,
		// so measure again; then pull it back inside the window if it sticks
		// out at the side, with the arrow still pointing at the element
		var actualWidth = tip.offsetWidth;
		var actualHeight = tip.offsetHeight;
		if (actualHeight !== height) top = top + height - actualHeight;
		var delta = 0;
		if (left < 0) {
			delta = -left;
		} else if (left + actualWidth > document.body.getBoundingClientRect().right) {
			delta = document.documentElement.clientWidth - (left + actualWidth);
		}
		moveTo(tip, top, left + delta, false);
		tip.firstChild.style.left = 50 * (1 - (delta * 2 - width + actualWidth) / tip.offsetWidth) + '%';
	}

	function hide(el) {
		var tip = el._tooltip;
		if (!tip) return;
		tip.className = 'tooltip top';
		tip.removeTimer = setTimeout(function () {
			tip.parentNode.removeChild(tip);
			el.removeAttribute('aria-describedby');
			el._tooltip = null;
		}, FADE_MS);
	}

	var elements = document.querySelectorAll('[data-toggle="tooltip"]');
	for (var i = 0; i < elements.length; i++) {
		(function (el) {
			// Keep the title out of the browser's own popup while ours is in use
			el.setAttribute('data-original-title', el.getAttribute('title') || '');
			el.setAttribute('title', '');
			el.addEventListener('mouseenter', function () { show(el); });
			el.addEventListener('focusin', function () { show(el); });
			el.addEventListener('mouseleave', function () { hide(el); });
			el.addEventListener('focusout', function () { hide(el); });
		})(elements[i]);
	}
})();
