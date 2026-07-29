import pikepdf

from .utils import get_operator_coords, multiply_matrices, transform_point


def filter_page_content(page_obj, complex_bboxes_pdf_space, collect=None):
    """
    Parses the page content stream. Dynamically tracks the Coordinate Transformation Matrix (CTM)
    and text matrices. Strips path drawing operations inside complex bboxes, wraps path drawing
    operators outside complex bboxes inside '/Artifact', and filters text content inside complex bboxes.
    Yields blocks of instructions: ('text', ops), ('empty_text', ops), ('artifact', ops), or ('other', op).

    When ``collect`` is a dictionary, geometry observed while walking the stream
    is recorded into it without altering what is yielded:

    ``collect["images"]``
        ``(xobject name, Box)`` for every image drawn, in the page's coordinate
        space. An image XObject is drawn into the unit square, so its placement
        is exactly the transformation matrix in force at the time.
    ``collect["paths"]``
        A ``Box`` bounding each painted path, used to cluster vector artwork
        into candidate figures.

    Collecting during this walk avoids a second parse of the stream, and the
    transformation matrix is only available here.
    """
    from .geometry.boxes import Box

    images_out = collect.setdefault("images", []) if collect is not None else None
    paths_out = collect.setdefault("paths", []) if collect is not None else None

    def _record_path(points):
        if paths_out is None or not points:
            return
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        paths_out.append(Box(min(xs), min(ys), max(xs), max(ys)))

    def _record_image(name, matrix):
        if images_out is None:
            return
        corners = [
            transform_point(0.0, 0.0, matrix),
            transform_point(1.0, 0.0, matrix),
            transform_point(0.0, 1.0, matrix),
            transform_point(1.0, 1.0, matrix),
        ]
        xs = [x for x, _ in corners]
        ys = [y for _, y in corners]
        images_out.append((name, Box(min(xs), min(ys), max(xs), max(ys))))

    def _is_image_xobject(name):
        try:
            resources = page_obj.get("/Resources")
            xobjects = resources.get("/XObject") if resources is not None else None
            if xobjects is None:
                return False
            target = xobjects.get(name)
            return target is not None and str(target.get("/Subtype", "")) == "/Image"
        except Exception:
            return False

    try:
        instructions = pikepdf.parse_content_stream(page_obj)
    except Exception:
        return

    path_construction_ops = {"m", "l", "c", "v", "y", "h", "re"}
    path_painting_ops = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"}
    clipping_ops = {"W", "W*"}

    ctm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    ctm_stack = []

    t_m = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    t_lm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    t_leading = 0.0

    in_text_block = False
    text_block_ops = []
    has_visible_text = False

    path_buffer = []

    for operands, operator in instructions:
        op_name = str(operator)

        # Strip pre-existing marked content operators to avoid nesting structural blocks
        if op_name in ("BDC", "BMC", "EMC"):
            continue

        # Track CTM
        if op_name == "q":
            ctm_stack.append(list(ctm))
        elif op_name == "Q":
            if ctm_stack:
                ctm = ctm_stack.pop()
        elif op_name == "cm":
            if len(operands) >= 6:
                ctm = multiply_matrices([float(x) for x in operands], ctm)

        # Track text state
        if op_name == "BT":
            in_text_block = True
            text_block_ops = []
            has_visible_text = False
            t_m = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            t_lm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            t_leading = 0.0
            text_block_ops.append((operands, operator))
            continue

        if in_text_block:
            text_block_ops.append((operands, operator))

            # Update matrices
            if op_name == "Tm":
                if len(operands) >= 6:
                    t_m = [float(x) for x in operands]
                    t_lm = list(t_m)
            elif op_name in ("Td", "TD"):
                if len(operands) >= 2:
                    tx_o, ty_o = float(operands[0]), float(operands[1])
                    if op_name == "TD":
                        t_leading = -ty_o
                    t_lm = multiply_matrices([1.0, 0.0, 0.0, 1.0, tx_o, ty_o], t_lm)
                    t_m = list(t_lm)
            elif op_name == "T*":
                t_lm = multiply_matrices([1.0, 0.0, 0.0, 1.0, 0.0, -t_leading], t_lm)
                t_m = list(t_lm)
            elif op_name == "TL":
                if len(operands) >= 1:
                    t_leading = float(operands[0])
            elif op_name in ("'", '"'):
                tx_o, ty_o = 0.0, -t_leading
                t_lm = multiply_matrices([1.0, 0.0, 0.0, 1.0, tx_o, ty_o], t_lm)
                t_m = list(t_lm)

            # Perform text content visibility check for text showing operators
            if op_name in ("Tj", "TJ", "'", '"'):
                if op_name == "Tj":
                    if str(operands[0]).strip():
                        has_visible_text = True
                elif op_name == "TJ":
                    for item in operands[0]:
                        if isinstance(item, pikepdf.String):
                            if str(item).strip():
                                has_visible_text = True
                                break
                elif op_name in ("'", '"'):
                    if str(operands[-1]).strip():
                        has_visible_text = True

            if op_name == "ET":
                in_text_block = False
                if has_visible_text:
                    yield "text", text_block_ops
                else:
                    yield "empty_text", text_block_ops
            continue

        # Handle path operators
        if op_name in path_construction_ops or op_name in clipping_ops:
            path_buffer.append(((operands, operator), list(ctm)))
            continue

        if op_name in path_painting_ops:
            path_buffer.append(((operands, operator), list(ctm)))

            # Process the full path sequence in the buffer
            coords_pdf = []
            for (item_ops, item_op), item_ctm in path_buffer:
                item_op_name = str(item_op)
                coords_c = get_operator_coords(item_op_name, item_ops)
                for cx, cy in coords_c:
                    px, py = transform_point(cx, cy, item_ctm)
                    coords_pdf.append((px, py))

            inside_complex = False
            if coords_pdf:
                for px, py in coords_pdf:
                    for bbox in complex_bboxes_pdf_space:
                        bx0, by0, bx1, by1 = bbox
                        if bx0 <= px <= bx1 and by0 <= py <= by1:
                            inside_complex = True
                            break
                    if inside_complex:
                        break

            _record_path(coords_pdf)

            if not inside_complex:
                yield "artifact", [op_item for op_item, _ in path_buffer]

            path_buffer = []
            continue

        # Flush path buffer if other operator is met
        if path_buffer:
            inside_complex = False
            coords_pdf = []
            for (item_ops, item_op), item_ctm in path_buffer:
                item_op_name = str(item_op)
                coords_c = get_operator_coords(item_op_name, item_ops)
                for cx, cy in coords_c:
                    px, py = transform_point(cx, cy, item_ctm)
                    coords_pdf.append((px, py))
            if coords_pdf:
                for px, py in coords_pdf:
                    for bbox in complex_bboxes_pdf_space:
                        bx0, by0, bx1, by1 = bbox
                        if bx0 <= px <= bx1 and by0 <= py <= by1:
                            inside_complex = True
                            break
                    if inside_complex:
                        break
            _record_path(coords_pdf)
            if not inside_complex:
                yield "artifact", [op_item for op_item, _ in path_buffer]
            path_buffer = []

        # An image XObject is drawn into the unit square, so the transformation
        # matrix in force is precisely its placement on the page.
        if op_name == "Do" and operands:
            name = str(operands[0])
            if _is_image_xobject(name):
                _record_image(name, list(ctm))

        yield "other", (operands, operator)
