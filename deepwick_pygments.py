"""Deepwick Pygments style. pgcli uses it with syntax_style = deepwick."""
from pygments.style import Style
from pygments.token import Comment, Error, Keyword, Name, Number, Operator, Punctuation, String, Token


class DeepwickStyle(Style):
    name = "deepwick"
    background_color = "#04041a"
    highlight_color = "#264F78"
    styles = {
        Token: "#D4D4D4",
        Comment: "italic #7A86A8",
        Keyword: "#569CD6",
        Name.Builtin: "#4EC9B0",
        Name.Function: "#DCDCAA",
        Name.Variable: "#9CDCFE",
        String: "#CE9178",
        String.Escape: "#D7BA7D",
        String.Name: "#9CDCFE",
        Number: "#B5CEA8",
        Operator: "#D4D4D4",
        Operator.Word: "#569CD6",
        Punctuation: "#D4D4D4",
        Error: "#F44747",
        Token.Output.Header: "bold #569CD6",
        Token.Output.TableSeparator: "#6E7899",
        Token.Output.Null: "#6E7899",
    }
