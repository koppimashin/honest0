"""
This module provides functionality to create a "stealth" window using the pywin32 library.
A stealth window is a hidden, windowless application that can run in the background
without appearing in the taskbar or Alt-Tab switcher. This is useful for background
processes that need to interact with the Windows GUI environment without user visibility.
"""

import pywintypes
import win32con
import win32gui

class Stealth:
    """
    Manages the creation and behavior of a hidden, windowless application window.
    This window is designed to operate in the background without user interaction
    or visibility in the taskbar.
    """
    def __init__(self):
        """
        Initializes the Stealth class with default window properties.
        """
        self.window_class_name = "StealthAppWindowClass" # Unique class name for the window.
        self.window_title = "Stealth App" # Title for the window (though it will be hidden).
        self.hwnd = None # Handle to the created window.

    def make_windowless(self):
        """
        Creates a hidden, windowless window.
        This involves registering a window class, creating the window, and then
        modifying its extended styles to hide it from the taskbar and Alt-Tab,
        and making it transparent.
        """
        wc = win32gui.WNDCLASS()
        wc.hInstance = win32gui.GetModuleHandle(None) # Get instance handle of the current process.
        wc.lpszClassName = self.window_class_name # Assign the custom class name.
        wc.style = win32con.CS_VREDRAW | win32con.CS_HREDRAW # Redraw on vertical/horizontal size change.
        wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW) # Set default cursor.
        wc.lpfnWndProc = self.WndProc  # Assign the window procedure callback.

        try:
            class_atom = win32gui.RegisterClass(wc) # Register the window class.
        except pywintypes.error as e:
            if e.args[0] == 1410:  # ERROR_CLASS_ALREADY_EXISTS
                # This error means the class is already registered, which is fine.
                pass
            else:
                raise # Re-raise other unexpected errors.

        # Create the window with minimal style and zero dimensions.
        self.hwnd = win32gui.CreateWindow(
            self.window_class_name, # Window class name.
            self.window_title,      # Window title.
            win32con.WS_OVERLAPPED | win32con.WS_SYSMENU, # Basic window style (can be minimal).
            0, 0,  # x, y position (top-left corner).
            0, 0,  # width, height (zero for windowless).
            0,  # hWndParent (no parent window).
            0,  # hMenu (no menu).
            wc.hInstance, # Instance handle.
            None # No creation parameters.
        )
        
        # Hide the window from the taskbar and Alt-Tab switcher.
        win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE) # Hide the window initially.
        # Set extended window styles:
        # WS_EX_TOOLWINDOW: Excludes the window from the taskbar and Alt-Tab.
        # WS_EX_LAYERED: Enables the use of SetLayeredWindowAttributes for transparency.
        win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE,
                               win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE) |
                               win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_LAYERED)
        # Make the window fully transparent (alpha 0) and use color key (0) for transparency.
        win32gui.SetLayeredWindowAttributes(self.hwnd, 0, 0, win32con.LWA_ALPHA)

    def WndProc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        """
        The window procedure callback function for the hidden window.
        Handles Windows messages sent to the window.

        Args:
            hwnd (int): The handle to the window.
            msg (int): The message code.
            wparam (int): The first message parameter.
            lparam (int): The second message parameter.

        Returns:
            int: The result of the message processing.
        """
        if msg == win32con.WM_DESTROY:
            # When the window is being destroyed, post a quit message to terminate the message loop.
            win32gui.PostQuitMessage(0)
        else:
            # For any other messages, pass them to the default window procedure.
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

def main():
    """
    Main function to demonstrate the creation of a stealth window.
    It creates a Stealth instance, makes the windowless, and then
    starts a message pump to process Windows messages.
    """
    stealth = Stealth()
    stealth.make_windowless()
    # Start the message loop to allow the window to process messages.
    # This keeps the application running in the background.
    win32gui.PumpWaitingMessages()

if __name__ == '__main__':
    main()