from rich.text import Text

from mantui.theme.colors import GREEN

LOGO = r"""
███╗   ███╗ █████╗ ███╗   ██╗████████╗██╗   ██╗██╗  '-.          ,-' 
████╗ ████║██╔══██╗████╗  ██║╚══██╔══╝██║   ██║██║     '.      ,'   
██╔████╔██║███████║██╔██╗ ██║   ██║   ██║   ██║██║       \    /    
██║╚██╔╝██║██╔══██║██║╚██╗██║   ██║   ██║   ██║██║      (,\--/,)  
██║ ╚═╝ ██║██║  ██║██║ ╚████║   ██║   ╚██████╔╝██║       \Y  Y/   
╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═╝        `><'     
"""


def create_logo() -> Text:
    """Return the branded logo renderable without imposing alignment."""
    return Text(
        LOGO.strip("\n"),
        style=f"bold {GREEN}",
    )

     
                                                
                                                 
                                               
                                         
