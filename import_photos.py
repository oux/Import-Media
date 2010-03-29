#!/usr/bin/python2.6

# dependences:
# imagemagick
# exif
# exiftran
# pmount

from __future__ import print_function
import pygtk
pygtk.require('2.0')
import gtk
from syslog import *
import curses
import os, re,subprocess, shutil
import filecmp
import dbus
import gobject
#Modules pour le multithreading
import thread,threading
import time

#Important : Initialisation pour l'utilisation de threads
gtk.gdk.threads_init()

debug = False

class DeviceAddedListener:
  def __init__(self,app):
    print('dbus init')
    self.bus = dbus.SystemBus()
    self.hal_manager_obj = self.bus.get_object(
                        "org.freedesktop.Hal",
                        "/org/freedesktop/Hal/Manager")
    self.hal_manager = dbus.Interface(self.hal_manager_obj,
                      "org.freedesktop.Hal.Manager")
    self.hal_manager.connect_to_signal("DeviceAdded", self._filter)
    self.app = app


  def _filter(self, udi):
    device_obj = self.bus.get_object ("org.freedesktop.Hal", udi)
    device = dbus.Interface(device_obj, "org.freedesktop.Hal.Device")

    if device.QueryCapability("volume"):
      return self.do_something(device)

  def do_something(self, volume):
    mount_point = None
    device_file = volume.GetProperty("block.device")
    label = volume.GetProperty("volume.label")
    fstype = volume.GetProperty("volume.fstype")
    mounted = volume.GetProperty("volume.is_mounted")
    try:
      size = volume.GetProperty("volume.size")
    except:
      size = 0

    print ("New storage device detected:")
    print ("  device_file: %s" % device_file)
    print ("  label: %s" % label)
    print ("  fstype: %s" % fstype)
    if not mounted:
      print ("  not mounted ... mounting" )
      self.app.MountDevice(device_file)
    mount_point = volume.GetProperty("volume.mount_point")
    print ("  mount_point: %s" % mount_point)
    print ("  size: %s (%.2fGB)" % (size, float(size) / 1024**3))
    self.app.mainlabel.set_text(device_file)
    # t = thread.start_new_thread(loop_test, ())
    t = threading.Thread(target=self.app.ImportPhotos, args=(device_file,mount_point))
    # t = threading.Thread(target=self.app.loop_test, args=(device_file,mount_point))
    t.start()

class exif():
  """ Objet permettant de gerer les tags exifs
  d'une image et de comparer deux images sur les criteres exifs:
    * comparaison plus rapide
    * Permet d'identifier deux images identiques meme si elle est tournee.
  """
  def __init__(self,name=None):
    self.attributs = dict()
    if name is not None:
      if os.path.isfile(name):
        ret = subprocess.Popen(["exif", name],env={"LC_ALL":"C" },stderr=subprocess.PIPE,stdout=subprocess.PIPE).communicate()[0]
        attrs = ret.splitlines()[4:]
        attrs = attrs[:-2]
        for attr in attrs:
          try:
            (key, value) = attr.split('|')
          except:
            continue
          if debug: print(key,value)
          self.attributs [ key.strip() ] = value.strip()

  def get(self,attr):
    try:
      return self.attributs[attr]
    except:
      return None

  def __eq__(self, other):
    ret = True
    for attr in self.attributs.keys():
      if attr not in [ 'Maker Note', 'Orientation', 'PixelXDimension', 'PixelYDimension' ]:
        pass
        if self.get(attr) != other.get(attr):
          ret = False
          break
    if ret:
      return True

class ImportApp():

  align = gtk.Alignment()
  directories = list()

  def __init__(self):
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)

    self.thumbnails_dir = 'PREVIEW'
    self.path_dest   = '/home/users/maison/media/images/photos'

    self.root = gtk.Window()
    self.root.connect("destroy", lambda w: gtk.main_quit())
    openlog('import_photo.py',LOG_INFO)
    self.root.set_title("Import des photos")
    self.vbox = gtk.VBox(False, 2)
    self.vbox.set_border_width(10)
    self.root.add(self.vbox)
    self.vbox.show()

    # Create a centering alignment object
    self.align = gtk.Alignment(0.5, 0.5, 0, 0)
    self.vbox.pack_start(self.align, False, False, 5)
    self.align.show()

    self.mainlabel = gtk.Label('Importation des photos')
    self.mainlabel.set_justify(gtk.JUSTIFY_CENTER)
    # vbox.pack_start(self.mainlabel, False, False, 0)
    # self.align.add(self.mainlabel)
    self.vbox.pack_start(self.mainlabel, False, False, 1)
    self.mainlabel.show()

    # Bstart = gtk.Button("Start")
    # Bstart.connect("clicked", init_thread)
    # vbox.pack_start(Bstart, False, False, 0)
    # Bstart.show()

    self.root.show()
    self.WaitingForDevice()

  def ImportPhotos(self,device_file=None,mount_point=None):
    # Create the ProgressBar
    bar = gtk.ProgressBar()
    # self.align.add(bar)
    self.vbox.pack_start(bar, False, False, 1)
    bar.show()

    bar.set_text('Importation des photos...')
    path_source = '%s/dcim' % mount_point
    # Recuperation des images
    compteur_files = 0
    total_files  = sum(list(len(i[2]) for i in list(os.walk(path_source))))
    date_pattern = re.compile(r'(\d+):(\d+):(\d+)')
    print("Nombre de fichier a traiter: %s" % total_files)

    if total_files == 0:
      bar.set_fraction(1)

    for rootpath, dirs, files in os.walk(path_source):
      for name in sorted(files):
        act = False
        # Affichage du nom de fichier
        print(name, end=" :")
        compteur_files += 1
        if total_files != 0:
          bar.set_fraction(float(compteur_files) / total_files)
          bar.set_text('%s : %d/%d' %(device_file,compteur_files, total_files))
        source = "%s/%s" % (rootpath, name)
        if debug: print("%s ..." % source)
        source_exif = exif(source)
        try:
          rel_directory = date_pattern.sub(r'\1\2\3',source_exif.get('Date and Time').split()[0])
        except:
          try:
            rel_directory = date_pattern.sub(r'\1\2\3',source_exif.get('Date and Time (origi').split()[0])
          except:
            print()
            continue
        if rel_directory not in self.directories:
          print(rel_directory,end=" ")
          self.directories.append(rel_directory)
        directory = "%s/%s" % (self.path_dest, rel_directory)
        destination_initiale = "%s/%s" % (directory, name)

        destination = destination_initiale
        compteur = 1
        must_copy = True

        # Creation du repertoire de destination avec le repertoire des images
        # redimensionnees
        if not os.path.isdir("%s/%s" % (directory, self.thumbnails_dir)):
          os.makedirs("%s/%s" % (directory, self.thumbnails_dir))

        # Recherche du nom de fichier de destination:
        #  * Pour eviter d'ecraser un fichier different mais de meme nom
        #  * Pour ne pas faire la copie si le fichier a deja ete transfere
        while os.path.isfile(destination):
          if debug: print("Fichier %s existant" % destination)
          if not source_exif == exif(destination):
            if debug: print("Fichier %s different de la source" % destination)
            compteur += 1
            destination = re.sub(r'(\.[^\.]*)$',r'_%s\1' % compteur,destination_initiale)
          else:
            if debug: print("Fichier %s identique a la source" % destination)
            must_copy = False
            break

        thumbnails = "%s/%s/%s" % (os.path.dirname(destination), self.thumbnails_dir, os.path.basename(destination))
        # Faire la copie, la rotation et le redimensionnement si necessaire
        if must_copy:
          act = True
          syslog('%s => %s' % (source, destination))
          if debug: print(source, "=>", destination)
          print("Import", end=" ")
          shutil.copy(source, destination)
        dest_exif = exif(destination)
        if dest_exif.get('Orientation') != "top - left" and dest_exif.get('Orientation') != None:
          act = True
          syslog('Rotation: %s' % destination)
          print("Rotation", end=" ")
          subprocess.Popen(["exiftran", "-a", "-i", destination],stderr=subprocess.PIPE,stdout=subprocess.PIPE).communicate()
        if not os.path.isfile(thumbnails):
          act = True
          syslog('Redimensionnement: %s' % thumbnails)
          print("Redimensionnement", end=" ")
          (stdoutdata, stderrdata) = subprocess.Popen(
              ["convert", "-resize", "1024x1024", destination, thumbnails],stdin=subprocess.PIPE,stderr=subprocess.PIPE, stdout=subprocess.PIPE
              ).communicate()
        if not act:
          syslog('%s = Rien a faire' % source)
          print("Rien a faire",end="")
        print()
    bar.set_text('Fin de l\'importation...')
    self.UmountDevice(device_file)

  def MountDevice(self,device_file):
    self.mainlabel.set_text('Montage de %s' % device_file)
    ret = subprocess.Popen(["/usr/bin/pmount", device_file], stdout=subprocess.PIPE, stderr=subprocess.STDOUT).communicate()[0]
    if ret is not None: print ('montage device %s %s' % (device_file,ret))

  def UmountDevice(self,device_file):
    self.mainlabel.set_text('Demontage de %s' % device_file)
    ret = subprocess.Popen(["/usr/bin/pumount", device_file], stdout=subprocess.PIPE, stderr=subprocess.STDOUT).communicate()[0]
    if ret is not None: print ('demontage device %s %s' % (device_file,ret))


  def WaitingForDevice(self):
    self.mainlabel.set_text('waiting for device...')
    DeviceAddedListener(self)

  def loop_test(self,device_file, mount_point):
    # Create the ProgressBar
    bar = gtk.ProgressBar()
    self.vbox.pack_start(bar, False, False, 1)
    bar.show()

    count=0
    while(1):
      count = count + 1
      time.sleep(1)
      if count >= 0 and count <= 3:
        bar.set_text("Initialisation...")
      elif count >= 3 and count <= 30:
        bar.set_text("Traitement en cours de %s ... %d" % (mount_point,count))
      elif count >= 30:
        bar.set_text("Traitement termine!")
        return(0)
      print( "%s => %s" % ( count, float(count)/30))
      #On update la progressbar
      bar.set_fraction(float(count) / 30)
    self.UmountDevice(device_file)

if __name__ == "__main__":
  ImportApp()
  gtk.main()
  print('bye')
  closelog()

  # TODO:
  # Recuperation des videos:
  #  - parametrage des extensions (avi, 3gp, MTS)
  #  - classer dans les repertoires par date de creation de fichier.
  #  - dest paramétrable et différentiable des images

  # Proposer une ihm permettant de saisir des commentaires pour l'integrer au nom du repertoire (date - commentaire)
  # Suppression de la source (avec verif d'intégrité -problème de comparaison apres rotation de l'image cf image magick-).
  # Message box pour confirmation d'import avant de comment.
  # Mettre en place le Model Vue Controleur
  # Résoudre les problèmes de symétrie.
  # S'inspirer du hotplug udev pour la version daemon : /etc/udev/hdparm.rules

  # Refs:
  # http://www.pygtk.org/pygtk2tutorial/sec-ProgressBars.html
  # http://majorsilence.com/pygtk_dbus_interprocess_communication


# vim: sw=2:tw=0:ts=2
