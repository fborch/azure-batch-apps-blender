﻿#-------------------------------------------------------------------------
#
# Batch Apps Blender Addon
#
# Copyright (c) Microsoft Corporation.  All rights reserved.
#
# MIT License
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the ""Software""), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED *AS IS*, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
#--------------------------------------------------------------------------

import bpy
import os

import threading

from batched_blender.utils import BatchOps
from batched_blender.ui import ui_history
from batched_blender.props import props_history

import azure.batch as batch


class BatchHistory(object):
    """
    Manger for the retrival and display of the users job history.
    """

    pages = ["HISTORY", "LOADING"]

    def __init__(self, manager):

        self.batch = manager
        self.ops = self._register_ops()
        self.props = self._register_props()
        self.ui = self._register_ui()

    def display(self, ui, layout):
        """
        Invokes the corresponding ui function depending on the session's
        current page.

        :Args:
            - ui (blender :class:`.Interface`): The instance of the Interface
              panel class.
            - layout (blender :class:`bpy.types.UILayout`): The layout object,
              derived from the Interface panel. Used for creating ui
              components.

        :Returns:
            - Runs the display function for the applicable page.
        """
        return self.ui[bpy.context.scene.batch_session.page](ui, layout)

    def _register_props(self):
        """
        Registers and retrieves the history property objects.
        The dispaly properties are defined in a subclass which is assigned
        to the scene.batch_history context.

        :Returns:
            - :class:`.HistoryProps`
        """
        props = props_history.register_props()
        return props

    def _register_ops(self):
        """
        Registers each job history operator with a batch_history prefix.

        :Returns:
            - A list of the names (str) of the registered job history
              operators.
        """
        ops = []
        ops.append(BatchOps.register("history.page",
                                         "Job history",
                                         self._history))
        #ops.append(BatchOps.register("history.first",
        #                                 "Beginning",
        #                                 self._first))
        #ops.append(BatchOps.register("history.last",
        #                                 "End",
        #                                 self._last))
        #ops.append(BatchOps.register("history.more",
        #                                 "Next",
        #                                 self._more))
        #ops.append(BatchOps.register("history.less",
        #                                 "Previous",
        #                                 self._less))
        ops.append(BatchOps.register("history.refresh",
                                         "Refresh",
                                         self._refresh))
        ops.append(BatchOps.register("history.end",
                                         "Finish job",
                                         self._end))
        ops.append(BatchOps.register("history.delete",
                                         "Delete job",
                                         self._delete))
        ops.append(BatchOps.register("history.import",
                                         "Import Sequence",
                                         self._import))
        ops.append(BatchOps.register("history.loading",
                                         "Loading job history",
                                         modal=self._loading_modal,
                                         invoke=self._loading_invoke,
                                         _timer=None))
        return ops

    def _register_ui(self):
        """
        Matches the history and loading pages with their corresponding
        ui functions.

        :Returns:
            - A dictionary mapping the page name to its corresponding
              ui function.
        """
        def get_history_ui(name):
            name = name.lower()
            return getattr(ui_history, name)

        page_func = map(get_history_ui, self.pages)
        return dict(zip(self.pages, page_func))

    def _loading_modal(self, op, context, event):
        """
        The modal method for the history.loading operator to handle running
        the downloading of the job history data in a separate thread to
        prevent the blocking of the Blender UI.

        :Args:
            - op (:class:`bpy.types.Operator`): An instance of the current
              operator class.
            - context (:class:`bpy.types.Context`): The current blender
              context.
            - event (:class:`bpy.types.Event`): The blender invocation event.

        :Returns:
            - If the thread has completed, the Blender-specific value
              {'FINISHED'} to indicate the operator has completed its action.
            - Otherwise the Blender-specific value {'RUNNING_MODAL'} to
              indicate the operator wil continue to process after the
              completion of this function.
        """
        if event.type == 'TIMER':
            context.scene.batch_session.log.debug("HistoryThread complete.")
            if not self.props.thread.is_alive():
                context.window_manager.event_timer_remove(op._timer)
            return {'FINISHED'}

        return {'RUNNING_MODAL'}

    def _loading_invoke(self, op, context, event):
        """
        The invoke method for the history.loading operator.
        Starts the job data retrieval thread.

        :Args:
            - op (:class:`bpy.types.Operator`): An instance of the current
              operator class.
            - context (:class:`bpy.types.Context`): The current blender
              context.
            - event (:class:`bpy.types.Event`): The blender invocation event.

        :Returns:
            - Blender-specific value {'RUNNING_MODAL'} to indicate the operator
              wil continue to process after the completion of this function.
        """
        self.props.thread.start()
        context.scene.batch_session.log.debug("HistoryThread initiated.")

        context.window_manager.modal_handler_add(op)
        op._timer = context.window_manager.event_timer_add(1, context.window)
        return {'RUNNING_MODAL'}

    def _history(self, op, context, *args):
        """
        The execute method for the history.page operator.
        Sets the functions to be performed by the job data retrieval thread
        and updates the session page to "LOADING" while the thread executes.

        Also resets the job display paging controls.

        :Args:
            - op (:class:`bpy.types.Operator`): An instance of the current
              operator class.
            - context (:class:`bpy.types.Context`): The current blender
              context.

        :Returns:
            - Blender-specific value {'FINISHED'} to indicate the operator has
              completed its action.
        """
        self.props.display = context.scene.batch_history
        self.props.display.selected = -1
        #self.props.display.index = 0
        #self.props.display.total_count = 0

        history_thread = lambda: BatchOps.session(self.get_job_list)
        self.props.thread = threading.Thread(name="HistoryThread",
                                             target=history_thread)

        bpy.ops.batch_history.loading('INVOKE_DEFAULT')

        if context.scene.batch_session.page == "HOME":
            context.scene.batch_session.page = "LOADING"

        return {'FINISHED'}

    #def _first(self, op, context, *args):
    #    """
    #    The execute method for the history.first operator.
    #    Resets the job display paging index to 0 (to display the first jobs
    #    in the list) and re-loads the accompanying job data.

    #    :Args:
    #        - op (:class:`bpy.types.Operator`): An instance of the current
    #          operator class.
    #        - context (:class:`bpy.types.Context`): The current blender
    #          context.

    #    :Returns:
    #        - Blender-specific value {'FINISHED'} to indicate the operator has
    #          completed its action.
    #    """
    #    #self.props.display.index = 0
    #    self.get_job_list()
    #    return {'FINISHED'}

    #def _last(self, op, context, *args):
    #    """
    #    The execute method for the history.last operator.
    #    Resets the job display paging controls to display the last jobs
    #    in the list and re-loads the accompanying job data.

    #    :Args:
    #        - op (:class:`bpy.types.Operator`): An instance of the current
    #          operator class.
    #        - context (:class:`bpy.types.Context`): The current blender
    #          context.

    #    :Returns:
    #        - Blender-specific value {'FINISHED'} to indicate the operator has
    #          completed its action.
    #    """
    #    settings = self.props.display

    #    if (settings.total_count % settings.per_call) == 0:
    #        settings.index = settings.total_count - settings.per_call

    #    else:
    #        div = settings.per_call - (settings.total_count % settings.per_call)
    #        settings.index = settings.total_count - settings.per_call + div
        
    #    self.get_job_list()
    #    return {'FINISHED'}

    #def _more(self, op, context, *args):
    #    """
    #    The execute method for the history.more operator.
    #    Resets the job display paging controls to display the subsequent jobs
    #    in the list and re-loads the accompanying job data.

    #    :Args:
    #        - op (:class:`bpy.types.Operator`): An instance of the current
    #          operator class.
    #        - context (:class:`bpy.types.Context`): The current blender
    #          context.

    #    :Returns:
    #        - Blender-specific value {'FINISHED'} to indicate the operator has
    #          completed its action.
    #    """
    #    self.props.display.index = self.props.display.index + self.props.display.per_call
    #    self.get_job_list()
    #    return {'FINISHED'}

    #def _less(self, op, context, *args):
    #    """
    #    The execute method for the history.less operator.
    #    Resets the job display paging controls to display the previous jobs
    #    in the list and re-loads the accompanying job data.

    #    :Args:
    #        - op (:class:`bpy.types.Operator`): An instance of the current
    #          operator class.
    #        - context (:class:`bpy.types.Context`): The current blender
    #          context.

    #    :Returns:
    #        - Blender-specific value {'FINISHED'} to indicate the operator has
    #          completed its action.
    #    """
    #    self.props.display.index = self.props.display.index - self.props.display.per_call
    #    self.get_job_list()
    #    return {'FINISHED'}

    def _refresh(self, op, context, *args):
        """
        The execute method for the history.refresh operator.
        Re-loads the current job data.

        :Args:
            - op (:class:`bpy.types.Operator`): An instance of the current
              operator class.
            - context (:class:`bpy.types.Context`): The current blender
              context.

        :Returns:
            - Blender-specific value {'FINISHED'} to indicate the operator has
              completed its action.
        """
        self.get_job_list()
        return {'FINISHED'}

    def _import(self, op, context, *args):
        job = self.get_selected_job()
        context.scene.batch_session.log.debug(
            "Selected job {0}".format(job.id))
        tasks = self.batch.task.list(job.id)
        prefix = job.display_name
        temp_dir = context.user_preferences.filepaths.temporary_directory
        output_dir = os.path.join(temp_dir, job.id)
        if not os.path.exists(output_dir):
            os.mkdir(output_dir)
        downloaded = []
        print("Output directory", output_dir)
        for t in tasks:
            files = self.batch.file.list_from_task(job.id, t.id, recursive=True)
            for f in files:
                if f.is_directory:
                    continue
                if not f.name.startswith('wd/' + prefix):
                    continue
                file_name = os.path.join(output_dir, f.name.split('/')[-1])
                print("Downloading", file_name)
                if not os.path.exists(file_name):
                    with open(file_name, 'wb') as handle:
                        response = self.batch.file.get_from_task(job.id, t.id, f.name)
                        for data in response:
                            handle.write(data)
                downloaded.append(file_name)

        context.scene.sequence_editor_clear()
        context.scene.sequence_editor_create()
        frame = context.scene.batch_submission.start_f #TODO: Get proper frame range based on filename
        for index, file in enumerate(downloaded):
            context.scene.sequence_editor.sequences.new_image(job.id, filepath=file, channel=1, frame_start=frame)
            frame += 1
        return {'FINISHED'}



    def _delete(self, op, context, *args):
        job = self.get_selected_job()
        context.scene.batch_session.log.debug(
            "Selected job {0}".format(job.id))

        self.batch.job.delete(job.id)
        #job.update()
        context.scene.batch_session.log.info(
            "Deleted with ID: {0}".format(job.id))

        return {'FINISHED'}

    def _end(self, op, context, *args):
        """
        The execute method for the history.cancel operator.
        Cancels the currently selected job.

        :Args:
            - op (:class:`bpy.types.Operator`): An instance of the current
              operator class.
            - context (:class:`bpy.types.Context`): The current blender
              context.

        :Returns:
            - Blender-specific value {'FINISHED'} to indicate the operator has
              completed its action.
        """
        job = self.get_selected_job()
        context.scene.batch_session.log.debug(
            "Selected job {0}".format(job.id))

        self.batch.job.terminate(job.id)
        #job.update()
        context.scene.batch_session.log.info(
            "Completed with ID: {0}".format(job.id))

        return {'FINISHED'}

    def get_selected_job(self):
        """
        Retrieves the job object for the job currently selected in
        the dispaly.

        :Returns:
            - A :class:`batch.jobs.SubmittedJob` object.
        """
        return self.props.job_list[self.props.display.selected]

    def get_job_list(self):
        """
        Downlaods a set of job data based on index and default per call parameter,
        assigns it to the property job_list and redraws the HISTORY page to
        display the new data.

        Each job is also registered as an operator class.
        #TODO: Unregister previous job classes?
        """
        self.props.job_list = []
        self.props.display.jobs.clear()

        bpy.context.scene.batch_session.log.debug(
            "Getting job data")

        latest_jobs = self.batch.job.list(batch.models.JobListOptions(max_results=self.props.display.per_call))
        latest_jobs = [j for j in latest_jobs if j.id.startswith("blender_render")]
        #latest_jobs = self.batch.get_jobs(
        #    index=self.props.display.index,
        #    per_call=self.props.display.per_call)

        for job in latest_jobs:
            self.props.job_list.append(job)
            self.props.display.add_job(job)

        #self.props.display.total_count = len(self.batch)
        for index, job in enumerate(self.props.display.jobs):
            self.register_job(job, index)

        bpy.context.scene.batch_session.log.info(
            "Retrieved {0} job "
            "listings.".format(len(latest_jobs)))

        bpy.context.scene.batch_session.page = "HISTORY"
        bpy.context.scene.batch_session.redraw()


    def register_job(self, job, index):
        """
        Register a job as an operator class for dispaly in the UI.

        :Args:
            - job (:class:`batch.jobs.SubmittedJob`): The job to register.
            - index (int): The index of the job in list currently displayed.

        :Returns:
            - The newly registered operator name (str).
        """
        name = "history.{0}".format(job.id.replace("-", "_").lower())
        label = "Job: {0}".format(job.name)
        index_prop = bpy.props.IntProperty(default=index)

        def execute(self):
            session = bpy.context.scene.batch_history
            bpy.context.scene.batch_session.log.debug(
                "Job details opened: {0}, selected: {1}, index {2}".format(
                    self.enabled,
                    session.selected,
                    self.ui_index))

            if self.enabled and session.selected == self.ui_index:
                session.selected = -1

            else:
                session.selected = self.ui_index

        bpy.context.scene.batch_session.log.debug(
            "Registering {0}".format(name))

        return BatchOps.register_expanding(name, label, execute,
                                               ui_index=index_prop)