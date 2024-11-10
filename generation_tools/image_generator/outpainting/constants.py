SPACE_IS_DOWN_ERRORS = ('The read operation timed out',)
QUOTA_EXCEEDED_ERRORS = ("The upstream Gradio app has raised an exception: 'You have exceeded your GPU quota")
DIFFUSERS_IMAGE_OUTPAINT_SPACE = 'fffiloni/diffusers-image-outpaint'

ALIGNMENT_MIDDLE = 'Middle'
ALIGNMENT_TOP, ALIGNMENT_BOTTOM = 'Top', 'Bottom'
ALIGNMENT_RIGHT, ALIGNMENT_LEFT = 'Right', 'Left'

VALID_ALIGNMENTS = (ALIGNMENT_MIDDLE, ALIGNMENT_TOP, ALIGNMENT_BOTTOM, ALIGNMENT_RIGHT, ALIGNMENT_LEFT)

OVERLAP_BY_ALIGNMENT = {
    ALIGNMENT_MIDDLE: {
        'overlap_left': True,
        'overlap_right': True,
        'overlap_top': True,
        'overlap_bottom': True
    },
    ALIGNMENT_TOP: {
        'overlap_left': False,
        'overlap_right': False,
        'overlap_top': True,
        'overlap_bottom': False
    },
    ALIGNMENT_BOTTOM: {
        'overlap_left': False,
        'overlap_right': False,
        'overlap_top': False,
        'overlap_bottom': True
    },
    ALIGNMENT_LEFT: {
        'overlap_left': True,
        'overlap_right': False,
        'overlap_top': False,
        'overlap_bottom': False
    },
    ALIGNMENT_RIGHT: {
        'overlap_left': False,
        'overlap_right': True,
        'overlap_top': False,
        'overlap_bottom': False
    }
}

DEFAULT_RESIZE_OPTIONS = ('Full', '50%', '33%', '25%')

