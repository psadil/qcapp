// Hotkey support for rating radio buttons in the form
// p: pass (0), u: unsure (1), f: fail (2), Enter: submit

document.addEventListener('DOMContentLoaded', function () {
    const form = document.getElementById('form');
    if (!form) return;

    // Get all radio inputs for the rating field
    const radios = Array.from(form.querySelectorAll('input[type="radio"][name="rating"]'));
    if (radios.length === 0) return;

    // Map hotkeys to values
    const hotkeyMap = {
        'p': '0', // pass
        'u': '1', // unsure
        'f': '2', // fail
    };

    // Helper: select radio by value
    function selectRadio(value) {
        const radio = radios.find(r => r.value === value);
        if (radio) {
            radio.checked = true;
            // Also trigger click on the label for Bootstrap styling
            const label = form.querySelector(`label[for='${radio.id}']`);
            if (label) label.click();
            radio.focus();
        }
    }

    document.addEventListener('keydown', function (e) {
        const active = document.activeElement;
        const tag = active.tagName;
        const key = e.key.toLowerCase();

        if (key === 'enter') {
            // Enter submits once a rating is chosen. Choosing a rating by
            // hotkey focuses its radio, so we must allow Enter from a focused
            // input here; only the comments textarea should get a newline.
            if (tag === 'TEXTAREA') return;
            const checked = radios.find(r => r.checked);
            if (checked) {
                form.requestSubmit ? form.requestSubmit() : form.submit();
                e.preventDefault();
            }
            return;
        }

        // Rating hotkeys should not fire while typing in a field. Radios and
        // checkboxes are not typing targets — and native validation focuses
        // the first radio when it blocks a submit, so hotkeys must keep
        // working from there.
        if (tag === 'TEXTAREA') return;
        if (tag === 'INPUT' && !['radio', 'checkbox'].includes(active.type)) return;
        if (hotkeyMap[key]) {
            selectRadio(hotkeyMap[key]);
            e.preventDefault();
        }
    });

    // Listen for form reset to blur any focused rating radio button
    form.addEventListener('reset', function () {
        const active = document.activeElement;
        if (radios.includes(active)) {
            active.blur();
        }
    });
});
