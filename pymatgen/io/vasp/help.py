"""Get help with VASP parameters from VASP wiki."""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup


class VaspDoc:
    """A VASP documentation helper."""

    def __init__(self) -> None:
        """Init for VaspDoc."""
        self.url_template = "http://www.vasp.at/wiki/index.php/%s"

    def print_help(self, tag: str) -> None:
        """
        Print the help for a TAG.

        Args:
            tag (str): Tag used in VASP.
        """
        print(self.get_help(tag))

    def print_jupyter_help(self, tag: str) -> None:
        """
        Display HTML help in ipython notebook.

        Args:
            tag (str): Tag used in VASP.
        """
        html_str = self.get_help(tag, "html")
        from IPython.core.display import HTML, display

        display(HTML(html_str))

    @classmethod
    def get_help(cls, tag: str, fmt: str = "text") -> str:
        """Get help on a VASP tag.

        Args:
            tag (str): VASP tag, e.g., ISYM.

        Returns:
            Help text.
        """
        tag = tag.upper()
        response = requests.get(f"https://www.vasp.at/wiki/index.php/{tag}", verify=False, timeout=600)
        soup = BeautifulSoup(response.text)
        main_doc = soup.find(id="mw-content-text")
        if fmt == "text":
            output = main_doc.text
            output = re.sub("\n{2,}", "\n\n", output)
        else:
            output = str(main_doc)

        return output

    @classmethod
    def get_incar_tags(cls) -> list[str]:
        """Returns: All incar tags."""
        tags = []
        for page in [
            "https://www.vasp.at/wiki/index.php/Category:INCAR",
            "https://www.vasp.at/wiki/index.php?title=Category:INCAR&pagefrom=ML+FF+LCONF+DISCARD#mw-pages",
        ]:
            response = requests.get(page, verify=False, timeout=600)
            soup = BeautifulSoup(response.text)
            for div in soup.findAll("div", {"class": "mw-category-group"}):
                children = div.findChildren("li")
                for child in children:
                    tags.append(child.text.strip())
        return tags


if __name__ == "__main__":
    doc = VaspDoc()
    doc.print_help("ISYM")
    print(doc.get_incar_tags())
