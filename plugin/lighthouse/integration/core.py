import os
import abc
import logging

from lighthouse.ui import *
from lighthouse.util import lmsg
from lighthouse.util.qt import *
from lighthouse.util.disassembler import disassembler, DisassemblerContextAPI

from lighthouse.metadata import DatabaseMetadata, metadata_progress
from lighthouse.exceptions import *

logger = logging.getLogger("Lighthouse.Core")

#------------------------------------------------------------------------------
# Plugin Metadata
#------------------------------------------------------------------------------

PLUGIN_VERSION = "0.9.0-DEV"
AUTHORS        = "Markus Gaasedelen"
DATE           = "2020"

#------------------------------------------------------------------------------
# Lighthouse Plugin Core
#------------------------------------------------------------------------------

class LighthouseCore(object):
    __metaclass__ = abc.ABCMeta

    #--------------------------------------------------------------------------
    # Initialization
    #--------------------------------------------------------------------------

    def load(self):
        """
        Load the plugin, and integrate its UI into the disassembler.
        """
        self.lighthouse_contexts = {}

        # the plugin color palette
        self.palette = LighthousePalette()
        self.palette.theme_changed(self.refresh_theme)

        def create_overview_instance(name, parent, data = None):
            print("Creating CoverageOverview instance ...") # TODO remove try/catch
            try:
                return CoverageOverview(self, parent, name, data)
            except Exception as e:
                logger.exception("Wid failed")

        # the coverage overview widget
        disassembler.create_dockable_widget("Coverage Overview", create_overview_instance)

        # install disassembler UI
        self._install_ui()

        # plugin loaded successfully, print the plugin banner
        self.print_banner()
        logger.info("Successfully loaded plugin")

    def unload(self):
        """
        Unload the plugin, and remove any UI integrations.
        """
        self._uninstall_ui()

        # spin donw any active contexts (stop threads, cleanup qt state, etc)
        for lctx in self.lighthouse_contexts:
            lctx.terminate()

        logger.info("-"*75)
        logger.info("Plugin terminated")

    @abc.abstractmethod
    def get_context(self, dctx):
        """
        Get the LighthouseContext object for a given disassembler context.
        """

        # create a new LighthouseContext if this is a new disassembler ctx / bv
        if id(dctx) not in self.lighthouse_contexts:
            self.lighthouse_contexts[id(dctx)] = LighthouseContext(self, dctx)

        # return the lighthouse context object for this disassembler ctx / bv
        return self.lighthouse_contexts[id(dctx)]

    def print_banner(self):
        """
        Print the plugin banner.
        """

        # build the main banner title
        banner_params = (PLUGIN_VERSION, AUTHORS, DATE)
        banner_title  = "Lighthouse v%s - (c) %s - %s" % banner_params

        # print plugin banner
        lmsg("")
        lmsg("-"*75)
        lmsg("---[ %s" % banner_title)
        lmsg("-"*75)
        lmsg("")

    #--------------------------------------------------------------------------
    # UI Integration (Internal)
    #--------------------------------------------------------------------------

    def _install_ui(self):
        """
        Initialize & integrate all plugin UI elements.
        """
        self._install_load_file()
        self._install_load_batch()
        self._install_open_coverage_xref()
        self._install_open_coverage_overview()

    def _uninstall_ui(self):
        """
        Cleanup & remove all plugin UI integrations.
        """
        self._uninstall_open_coverage_overview()
        self._uninstall_open_coverage_xref()
        self._uninstall_load_batch()
        self._uninstall_load_file()

    @abc.abstractmethod
    def _install_load_file(self):
        """
        Install the 'File->Load->Code coverage file...' menu entry.
        """
        pass

    @abc.abstractmethod
    def _install_load_batch(self):
        """
        Install the 'File->Load->Code coverage batch...' menu entry.
        """
        pass

    @abc.abstractmethod
    def _install_open_coverage_xref(self):
        """
        Install the right click 'Coverage Xref' context menu entry.
        """
        pass

    @abc.abstractmethod
    def _install_open_coverage_overview(self):
        """
        Install the 'View->Open subviews->Coverage Overview' menu entry.
        """
        pass

    @abc.abstractmethod
    def _uninstall_load_file(self):
        """
        Remove the 'File->Load file->Code coverage file...' menu entry.
        """
        pass

    @abc.abstractmethod
    def _uninstall_load_batch(self):
        """
        Remove the 'File->Load file->Code coverage batch...' menu entry.
        """
        pass

    @abc.abstractmethod
    def _uninstall_open_coverage_xref(self):
        """
        Remove the right click 'Coverage Xref' context menu entry.
        """
        pass

    @abc.abstractmethod
    def _uninstall_open_coverage_overview(self):
        """
        Remove the 'View->Open subviews->Coverage Overview' menu entry.
        """
        pass

    #--------------------------------------------------------------------------
    # UI Actions (Public)
    #--------------------------------------------------------------------------

    def refresh_theme(self):
        """
        Refresh UI facing elements to reflect the current theme.
        """
        for lctx in self.lighthouse_contexts.values():
            lctx.director.refresh_theme()
            lctx.coverage_overview.refresh_theme()
            lctx.painter.repaint()

    def open_coverage_overview(self, dctx):
        """
        Open the dockable 'Coverage Overview' dialog.
        """
        self.palette.warmup()
        lctx = self.get_context(dctx)

        # the coverage overview is already open & visible, simply refresh it
        if lctx.coverage_overview.visible:
            lctx.coverage_overview.refresh()
            return

        disassembler.show_dockable_widget(lctx.coverage_overview.m_name)

    def open_coverage_xref(self, dctx, address):
        """
        Open the 'Coverage Xref' dialog for a given address.
        """
        lctx = self.get_context(dctx)

        # show the coverage xref dialog
        dialog = CoverageXref(lctx.director, address)
        if not dialog.exec_():
            return

        # activate the user selected xref (if one was double clicked)
        if dialog.selected_coverage:
            lctx.director.select_coverage(dialog.selected_coverage)
            return

        # load a coverage file from disk
        disassembler.show_wait_box("Loading coverage from disk...")
        created_coverage, errors = lctx.director.load_coverage_files(
            [dialog.selected_filepath],
            disassembler.replace_wait_box
        )

        if not created_coverage:
            lmsg("No coverage files could be loaded...")
            disassembler.hide_wait_box()
            warn_errors(errors)
            return

        disassembler.replace_wait_box("Selecting coverage...")
        lctx.director.select_coverage(created_coverage[0].name)
        disassembler.hide_wait_box()

    def interactive_load_batch(self, ctx):
        """
        Perform the user-interactive loading of a coverage batch.
        """
        self.palette.warmup()
        lctx = self.get_context(dctx)

        #
        # kick off an asynchronous metadata refresh. this will run in the
        # background while the user is selecting which coverage files to load
        #

        future = lctx.metadata.refresh_async(progress_callback=metadata_progress)

        #
        # we will now prompt the user with an interactive file dialog so they
        # can select the coverage files they would like to load from disk
        #

        filepaths = lctx.select_coverage_files()
        if not filepaths:
            lctx.director.metadata.abort_refresh()
            return

        # prompt the user to name the new coverage aggregate
        default_name = "BATCH_%s" % lctx.director.peek_shorthand()
        ok, batch_name = prompt_string(
            "Batch Name:",
            "Please enter a name for this coverage",
            default_name
        )

        #
        # if user didn't enter a name for the batch (or hit cancel) we should
        # abort the loading process...
        #

        if not (ok and batch_name):
            lmsg("User failed to enter a name for the batch coverage...")
            lctx.director.metadata.abort_refresh()
            return

        #
        # to begin mapping the loaded coverage data, we require that the
        # asynchronous database metadata refresh has completed. if it is
        # not done yet, we will block here until it completes.
        #
        # a progress dialog depicts the work remaining in the refresh
        #

        disassembler.show_wait_box("Building database metadata...")
        lctx.metadata.go_synchronous()
        await_future(future)

        #
        # now that the database metadata is available, we can use the director
        # to normalize and condense (aggregate) all the coverage data
        #

        disassembler.replace_wait_box("Loading coverage from disk...")
        batch_coverage, errors = lctx.director.load_coverage_batch(
            filepaths,
            batch_name,
            disassembler.replace_wait_box
        )

        # if batch creation fails...
        if not batch_coverage:
            lmsg("Creation of batch '%s' failed..." % batch_name)
            disassembler.hide_wait_box()
            warn_errors(errors)
            return

        # select the newly created batch coverage
        disassembler.replace_wait_box("Selecting coverage...")
        lctx.director.select_coverage(batch_name)

        # all done! pop the coverage overview to show the user their results
        disassembler.hide_wait_box()
        lmsg("Successfully loaded batch %s..." % batch_name)
        self.open_coverage_overview(lctx.dctx)

        # finally, emit any notable issues that occurred during load
        warn_errors(errors)

    def interactive_load_file(self, dctx):
        """
        Perform the user-interactive loading of individual coverage files.
        """
        self.palette.warmup()
        lctx = self.get_context(dctx)

        #
        # kick off an asynchronous metadata refresh. this will run in the
        # background while the user is selecting which coverage files to load
        #

        future = lctx.metadata.refresh_async(progress_callback=metadata_progress)

        #
        # we will now prompt the user with an interactive file dialog so they
        # can select the coverage files they would like to load from disk
        #

        filenames = lctx.select_coverage_files()
        if not filenames:
            lctx.metadata.abort_refresh()
            return

        #
        # to begin mapping the loaded coverage data, we require that the
        # asynchronous database metadata refresh has completed. if it is
        # not done yet, we will block here until it completes.
        #
        # a progress dialog depicts the work remaining in the refresh
        #

        disassembler.show_wait_box("Building database metadata...")
        lctx.metadata.go_synchronous()
        await_future(future)

        #
        # now that the database metadata is available, we can use the director
        # to load and normalize the selected coverage files
        #

        disassembler.replace_wait_box("Loading coverage from disk...")
        created_coverage, errors = lctx.director.load_coverage_files(filenames, disassembler.replace_wait_box)

        #
        # if the director failed to map any coverage, the user probably
        # provided bad files. emit any warnings and bail...
        #

        if not created_coverage:
            lmsg("No coverage files could be loaded...")
            disassembler.hide_wait_box()
            warn_errors(errors)
            return

        #
        # activate the first of the newly loaded coverage file(s). this is the
        # one that will be visible in the coverage overview once opened
        #

        disassembler.replace_wait_box("Selecting coverage...")
        lctx.director.select_coverage(created_coverage[0].name)

        # all done! pop the coverage overview to show the user their results
        disassembler.hide_wait_box()
        lmsg("Successfully loaded %u coverage file(s)..." % len(created_coverage))
        self.open_coverage_overview(lctx.dctx)

        # finally, emit any notable issues that occurred during load
        warn_errors(errors)

    #--------------------------------------------------------------------------
    # Scheduled
    #--------------------------------------------------------------------------

    # TODO/REBASING
    @disassembler.execute_read
    def scheduled(self):
        metadata = self.director.metadata

        # get current imagebase
        base = disassembler.get_imagebase()
        lmsg("Imagebase: 0x%08x" % base)

        # detect an image rebase
        if (metadata.cached and base != metadata.imagebase) and not disassembler.busy:
            lmsg("Image rebase detected, rebasing Lighthouse metadata...")
            self.director.refresh()

        # schedule the next update
        self._scheduled.start(1000)
