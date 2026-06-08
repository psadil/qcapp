from django.forms.utils import flatatt
from django.forms.widgets import Widget
from django.utils import html


class RadioButtonSubmitWidget(Widget):
    """
    A widget that renders radio button choices as submit buttons.
    Each button submits the form when clicked with the selected value.
    """

    def __init__(self, choices=(), attrs=None):
        super().__init__(attrs)
        self.choices = list(choices)

    def format_value(self, value):
        """Return a value as it should appear when rendered in a template."""
        if value is None:
            return ""
        return str(value)

    def render(self, name, value, attrs=None, renderer=None):
        """Render the widget as HTML."""
        if attrs is None:
            attrs = {}

        # Add any additional attributes
        final_attrs = self.build_attrs(attrs)

        # Start building the HTML
        html_parts = []

        # Add a hidden input to store the current value
        hidden_input = html.format_html(
            '<input type="hidden" name="{}" value="{}" id="id_{}">',
            name,
            self.format_value(value),
            name,
        )
        html_parts.append(hidden_input)

        # Create buttons for each choice
        for option_value, option_label in self.choices:
            # Determine if this option is selected
            is_selected = (
                str(option_value) == str(value) if value is not None else False
            )

            # Build button attributes
            button_attrs = {
                "type": "submit",
                "name": f"{name}_submit",
                "value": str(option_value),
                "class": "radio-button-submit",
                "onclick": f"document.getElementById('id_{name}').value='{option_value}'; this.form.submit();",
            }

            # Add selected class if this option is currently selected
            if is_selected:
                button_attrs["class"] += " selected"

            # Create the button HTML
            button_html = html.format_html(
                "<button{}>{}</button>", flatatt(button_attrs), option_label
            )
            html_parts.append(button_html)

        return html.format_html("{}", "".join(html_parts))

    def value_from_datadict(self, data, files, name):
        """Extract the value from form data."""
        # Check if a submit button was clicked
        submit_key = f"{name}_submit"
        if submit_key in data:
            return data[submit_key]

        # Fallback to the hidden input value
        return data.get(name)
