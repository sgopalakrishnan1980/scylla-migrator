package com.scylladb.migrator

import org.apache.log4j.Logger

import java.lang.reflect.{InvocationHandler, Method, Proxy}
import scala.util.control.NonFatal

object SignalSupport {
  final case class Registration(restore: () => Unit)

  private final case class Api(signalClass: Class[_],
                               handlerClass: Class[_],
                               handleMethod: Method) {
    private def createSignal(name: String): AnyRef =
      signalClass
        .getConstructor(classOf[String])
        .newInstance(name)
        .asInstanceOf[AnyRef]

    def install(signalName: String, callback: String => Unit): Registration = {
      val handler = Proxy
        .newProxyInstance(
          handlerClass.getClassLoader,
          Array(handlerClass),
          new InvocationHandler {
            override def invoke(proxy: Any,
                                method: Method,
                                args: Array[AnyRef]): AnyRef = {
              if (method.getName == "handle" && args != null && args.nonEmpty) {
                callback(args(0).toString)
              }
              null
            }
          }
        )
        .asInstanceOf[AnyRef]

      val previous = handleMethod
        .invoke(null, createSignal(signalName), handler)
        .asInstanceOf[AnyRef]
      Registration(
        () => handleMethod.invoke(null, createSignal(signalName), previous))
    }
  }

  private def loadApi(): Option[Api] =
    Seq("jdk.internal.misc.Signal", "sun.misc.Signal").view.flatMap {
      signalClassName =>
        try {
          val signalClass = Class.forName(signalClassName)
          val handlerClass =
            Class.forName(s"${signalClass.getPackage.getName}.SignalHandler")
          val handleMethod =
            signalClass.getMethod("handle", signalClass, handlerClass)
          Some(Api(signalClass, handlerClass, handleMethod))
        } catch {
          case NonFatal(_) => None
        }
    }.headOption

  def installHandlers(signalNames: Seq[String], logger: Logger)(
      callback: String => Unit): Seq[Registration] =
    loadApi() match {
      case None =>
        logger.warn(
          "Signal handlers are unavailable on this JVM. Savepoints will still be written on schedule and at final shutdown.")
        Nil
      case Some(api) =>
        signalNames.flatMap { signalName =>
          try {
            Some(api.install(signalName, callback))
          } catch {
            case NonFatal(e) =>
              logger.warn(s"Could not install signal handler for $signalName",
                          e)
              None
          }
        }
    }
}
