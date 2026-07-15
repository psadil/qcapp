// Coarse-grid paint annotation controller.
//
// A fixed grid is overlaid on the image; the reviewer taps a cell to mark it
// (or drags to paint a swath) at the active level. Marked cells are UNSURE
// (amber) or FAIL (red), reusing the whole-image rating vocabulary; unmarked
// is PASS. Grid quantization is the whole point: there is deliberately no
// zoom, no vertices, no brush size — precision is not expressible.
//
// Pointer Events unify mouse/pen/touch, so this works with a finger. The
// controller is recreated for each image (htmx swaps the canvas partial into
// #main); the active level and the form wiring live at module scope and
// persist across swaps.

(function () {
    const UNSURE = 1;
    const FAIL = 2;
    const FILL = {
        [UNSURE]: "rgba(243, 156, 18, 0.45)", // amber
        [FAIL]: "rgba(231, 76, 60, 0.55)", // red
    };
    const GRID_LINE = "rgba(128, 128, 128, 0.30)";

    let activeRating = UNSURE;
    let controller = null;

    // ------------------------------------------------------------------ canvas
    const createController = () => {
        const canvas = document.getElementById("canvas");
        const wrapper = document.querySelector(".canvas-wrapper");
        if (!canvas || !wrapper) return null;

        const ctx = canvas.getContext("2d");
        const img = new Image();
        const cells = new Map(); // "col,row" -> rating
        const strokes = []; // undo history: each is Map(key -> prevRating|undefined)

        let gridCols = parseInt(canvas.dataset.gridCols || "28", 10);
        let gridRows = gridCols;
        let cellW = 1;
        let cellH = 1;
        let stroke = null; // Map(key -> prevRating) for the in-progress stroke
        let mode = null; // "paint" | "erase"

        const updateBadge = () => {
            const badge = document.getElementById("cell-count");
            if (badge) badge.textContent = String(cells.size);
        };

        const recomputeGrid = () => {
            cellW = img.width / gridCols;
            gridRows = Math.max(1, Math.round(img.height / cellW));
            cellH = img.height / gridRows;
        };

        const draw = () => {
            if (!ctx) return;
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(img, 0, 0);

            ctx.strokeStyle = GRID_LINE;
            ctx.lineWidth = 1;
            for (let c = 1; c < gridCols; c++) {
                const x = c * cellW;
                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x, canvas.height);
                ctx.stroke();
            }
            for (let r = 1; r < gridRows; r++) {
                const y = r * cellH;
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(canvas.width, y);
                ctx.stroke();
            }

            for (const [key, rating] of cells) {
                const [c, r] = key.split(",").map(Number);
                ctx.fillStyle = FILL[rating];
                ctx.fillRect(c * cellW, r * cellH, cellW, cellH);
            }
            updateBadge();
        };

        const resize = () => {
            if (!img.complete || !img.width) return;
            canvas.width = img.width;
            canvas.height = img.height;
            const displayW = wrapper.clientWidth;
            canvas.style.width = displayW + "px";
            canvas.style.height = (displayW * img.height) / img.width + "px";
            draw();
        };

        const cellAt = (clientX, clientY) => {
            const rect = canvas.getBoundingClientRect();
            const x = (clientX - rect.left) * (canvas.width / rect.width);
            const y = (clientY - rect.top) * (canvas.height / rect.height);
            const c = Math.min(gridCols - 1, Math.max(0, Math.floor(x / cellW)));
            const r = Math.min(gridRows - 1, Math.max(0, Math.floor(y / cellH)));
            return `${c},${r}`;
        };

        const applyTo = (key) => {
            if (stroke.has(key)) return; // each cell changes at most once per stroke
            stroke.set(key, cells.get(key));
            if (mode === "erase") cells.delete(key);
            else cells.set(key, activeRating);
        };

        const onDown = (e) => {
            e.preventDefault();
            canvas.setPointerCapture(e.pointerId);
            const key = cellAt(e.clientX, e.clientY);
            // Tapping a cell already at the active level clears it; otherwise paint.
            mode = cells.get(key) === activeRating ? "erase" : "paint";
            stroke = new Map();
            applyTo(key);
            draw();
        };
        const onMove = (e) => {
            if (!stroke) return;
            applyTo(cellAt(e.clientX, e.clientY));
            draw();
        };
        const onUp = () => {
            if (stroke && stroke.size) strokes.push(stroke);
            stroke = null;
            mode = null;
        };

        canvas.addEventListener("pointerdown", onDown);
        canvas.addEventListener("pointermove", onMove);
        canvas.addEventListener("pointerup", onUp);
        canvas.addEventListener("pointercancel", onUp);
        window.addEventListener("resize", resize);

        img.onload = () => {
            recomputeGrid();
            resize();
        };
        img.src = document.getElementById("image-data")?.value;

        return {
            undo() {
                const s = strokes.pop();
                if (!s) return;
                for (const [key, prev] of s) {
                    if (prev === undefined) cells.delete(key);
                    else cells.set(key, prev);
                }
                draw();
            },
            clear() {
                if (cells.size) strokes.push(new Map(cells));
                cells.clear();
                draw();
            },
            getSubmitData() {
                const arr = [];
                for (const [key, rating] of cells) {
                    const [c, r] = key.split(",").map(Number);
                    arr.push([c, r, rating]);
                }
                return { grid_cols: gridCols, grid_rows: gridRows, cells: arr };
            },
            destroy() {
                canvas.removeEventListener("pointerdown", onDown);
                canvas.removeEventListener("pointermove", onMove);
                canvas.removeEventListener("pointerup", onUp);
                canvas.removeEventListener("pointercancel", onUp);
                window.removeEventListener("resize", resize);
            },
        };
    };

    // ------------------------------------------------------------ module wiring
    const syncLevelUI = () => {
        document.querySelectorAll("[data-level]").forEach((btn) => {
            const on = Number(btn.dataset.level) === activeRating;
            btn.classList.toggle("active", on);
            btn.setAttribute("aria-pressed", on ? "true" : "false");
        });
    };

    const reinit = () => {
        if (controller) controller.destroy();
        controller = createController();
        syncLevelUI();
    };

    const wireControls = () => {
        document.querySelectorAll("[data-level]").forEach((btn) => {
            btn.addEventListener("click", () => {
                activeRating = Number(btn.dataset.level);
                syncLevelUI();
            });
        });
        document
            .getElementById("undo")
            ?.addEventListener("click", () => controller?.undo());
        document
            .getElementById("clear")
            ?.addEventListener("click", () => controller?.clear());

        // Inject the current cell selection into the htmx POST at request time.
        const form = document.getElementById("form");
        if (form) {
            form.addEventListener("htmx:configRequest", (e) => {
                if (!controller) return;
                const data = controller.getSubmitData();
                e.detail.parameters["grid_cols"] = data.grid_cols;
                e.detail.parameters["grid_rows"] = data.grid_rows;
                e.detail.parameters["cells"] = JSON.stringify(data.cells);
            });
        }

        document.addEventListener("keydown", (e) => {
            if (["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
            if (!controller) return; // only active on click pages
            const key = e.key.toLowerCase();
            if (key === "u") {
                activeRating = UNSURE;
                syncLevelUI();
                e.preventDefault();
            } else if (key === "f") {
                activeRating = FAIL;
                syncLevelUI();
                e.preventDefault();
            } else if (key === "enter") {
                const form = document.getElementById("form");
                if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
                e.preventDefault();
            }
        });
    };

    document.addEventListener("DOMContentLoaded", () => {
        wireControls();
        reinit();
        // Re-create the canvas controller each time htmx swaps in a new image.
        document.body.addEventListener("htmx:afterSettle", reinit);
    });
})();
