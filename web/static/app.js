// Thousands separators while typing in amount fields (<input data-format="amount">).
// "1080000,5" -> "1 080 000,5". The caret stays after the same digit it was after.
// A dot is ambiguous while typing ("1." may become "1.080" or "1.50"): it stays visible until
// three digits follow it (thousands separator, removed) or the field loses focus (decimal -> comma).
(function () {
  "use strict";

  function group(integer) {
    return integer.replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }

  function format(raw) {
    var cleaned = raw.replace(/[^\d,.]/g, "");
    var comma = cleaned.indexOf(",");
    if (comma !== -1) {
      // Comma is the decimal separator; every dot is a thousands separator.
      var integer = cleaned.slice(0, comma).replace(/\./g, "");
      var decimals = cleaned.slice(comma + 1).replace(/[.,]/g, "").slice(0, 2);
      return group(integer) + "," + decimals;
    }
    var lastDot = cleaned.lastIndexOf(".");
    if (lastDot !== -1 && cleaned.length - lastDot - 1 <= 2) {
      // Possibly decimal: keep the last dot, earlier dots are thousands separators.
      return group(cleaned.slice(0, lastDot).replace(/\./g, "")) + "." + cleaned.slice(lastDot + 1);
    }
    return group(cleaned.replace(/\./g, ""));
  }

  function finalize(value) {
    // On leaving the field a remaining dot can only be the decimal separator.
    return value.replace(/\.(\d{0,2})$/, function (_, d) { return d ? "," + d : ""; });
  }

  function digitsBefore(value, position) {
    return value.slice(0, position).replace(/[^\d,.]/g, "").length;
  }

  function caretAfterDigits(value, count) {
    if (count === 0) return 0;
    var seen = 0;
    for (var i = 0; i < value.length; i++) {
      if (/[\d,.]/.test(value[i])) seen++;
      if (seen === count) return i + 1;
    }
    return value.length;
  }

  function onInput(event) {
    var input = event.target;
    var before = digitsBefore(input.value, input.selectionStart || 0);
    var formatted = format(input.value);
    if (formatted !== input.value) {
      var removed = input.value.replace(/[^\d,.]/g, "").length - formatted.replace(/[^\d,.]/g, "").length;
      input.value = formatted;
      var caret = caretAfterDigits(formatted, Math.max(0, before - removed));
      input.setSelectionRange(caret, caret);
    }
  }

  function onBlur(event) {
    event.target.value = finalize(format(event.target.value));
  }

  window.claimsFormatAmount = { format: format, finalize: finalize };  // for tests

  // Forms with data-busy: after submit, disable the button and show a spinner with the given text.
  function onBusySubmit(event) {
    var form = event.target;
    var button = event.submitter || form.querySelector("button");
    if (!button || form.dataset.submitted) return;
    form.dataset.submitted = "1";
    setTimeout(function () {  // after the browser has read the button value
      button.disabled = true;
      button.innerHTML = '<span class="spinner small-spinner" aria-hidden="true"></span> ' + form.dataset.busy;
    }, 0);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var busyForms = document.querySelectorAll("form[data-busy]");
    for (var b = 0; b < busyForms.length; b++) busyForms[b].addEventListener("submit", onBusySubmit);
    var inputs = document.querySelectorAll('input[data-format="amount"]');
    for (var i = 0; i < inputs.length; i++) {
      inputs[i].setAttribute("inputmode", "decimal");
      inputs[i].addEventListener("input", onInput);
      inputs[i].addEventListener("blur", onBlur);
      if (inputs[i].value) inputs[i].value = finalize(format(inputs[i].value));
    }
  });
})();
